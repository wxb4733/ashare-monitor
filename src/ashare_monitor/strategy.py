"""低频策略引擎 + 模拟交易（Phase A：股息轮动起步）。

策略层职责：把选股器输出（信号/候选）变成"规则化目标持仓"。
当前实现：
- dividend_strategy：高股息率 TOP N 等权组合（screen_dividend 输出 → 目标持仓）
- execute_paper_trade：按现价模拟买入（整手），记录持仓与交易日志（SQLite）

合规说明：纯模拟（paper trading），不产生真实交易；低频月度/周度再平衡。
低频策略不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TargetPosition:
    code: str
    name: str
    weight: float       # 权重 %
    target_value: float  # 目标市值（元）

    def to_dict(self) -> dict:
        return {"code": self.code, "name": self.name,
                "weight": self.weight, "target_value": self.target_value}


def dividend_strategy(top_n: int = 10, capital: float = 100_000.0,
                      min_yield: float = 3.0) -> list[TargetPosition]:
    """高股息轮动策略：选股器 TOP N 等权。"""
    from .screen import screen_dividend

    hits = screen_dividend(top_n=top_n, min_yield=min_yield)
    if not hits:
        raise RuntimeError("高股息选股无结果（东财 push2 沙箱受限时本机直连可用）")
    weight = 100.0 / len(hits)
    per = capital / len(hits)
    return [TargetPosition(code=h.code, name=h.name,
                           weight=round(weight, 2),
                           target_value=round(per, 2))
            for h in hits]


def execute_paper_trade(targets: list[TargetPosition],
                        dry_run: bool = False) -> dict:
    """按现价模拟买入（整手），入库 paper_positions + paper_trades。

    :return: {"fills": [...], "total_cost": float, "rejected": [...]}
    """
    import sqlite3

    from .quotes import fetch_spot_quotes
    from .storage import get_conn

    codes = [t.code for t in targets]
    quotes = {}
    try:
        qs, src = fetch_spot_quotes(codes, market="ashare")
        quotes = {q.code: q for q in qs}
    except Exception as exc:  # noqa: BLE001
        logger.warning("行情获取失败: %s", exc)

    fills, rejected = [], []
    total = 0.0
    for t in targets:
        q = quotes.get(t.code)
        if q is None or not q.price:
            rejected.append({"code": t.code, "name": t.name, "reason": "行情缺失"})
            continue
        shares = int(t.target_value // q.price // 100) * 100  # 整手
        if shares <= 0:
            rejected.append({"code": t.code, "name": t.name,
                             "reason": f"资金不足一手（价 {q.price:.2f}）"})
            continue
        cost = shares * q.price
        total += cost
        fills.append({"code": t.code, "name": t.name, "shares": shares,
                      "price": round(q.price, 2), "cost": round(cost, 2),
                      "date": datetime.now().strftime("%Y-%m-%d")})
    if not dry_run:
        conn = get_conn()
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS paper_positions (
                    code TEXT PRIMARY KEY, name TEXT, shares INTEGER,
                    avg_cost REAL, updated TEXT)"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT, name TEXT, side TEXT, shares INTEGER,
                    price REAL, cost REAL, trade_date TEXT)"""
            )
            for f in fills:
                conn.execute(
                    "INSERT OR REPLACE INTO paper_positions "
                    "(code, name, shares, avg_cost, updated) VALUES (?,?,?,?,?)",
                    (f["code"], f["name"], f["shares"], f["price"],
                     f["date"]))
                conn.execute(
                    "INSERT INTO paper_trades "
                    "(code, name, side, shares, price, cost, trade_date) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (f["code"], f["name"], "buy", f["shares"], f["price"],
                     f["cost"], f["date"]))
    return {"fills": fills, "total_cost": round(total, 2),
            "rejected": rejected}


def load_paper_positions() -> list[dict]:
    """读取模拟持仓。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM paper_positions ORDER BY code").fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


# ===================== 组合回测（策略历史验证） =====================

# 给定标的列表（A 股）等权组合 vs 沪深 300 基准。
# 数据：标的用本地 K 线（load_klines），基准用 akshare 沪深 300 日 K。
# 统计：区间收益 / 年化 / 最大回撤 / 夏普 / 超额收益。


def _daily_returns(rows: list[dict]) -> list[tuple[str, float]]:
    """(date, 日收益率%) 序列。"""
    out = []
    for i in range(1, len(rows)):
        prev = rows[i - 1]["close"]
        if prev:
            out.append((rows[i]["date"],
                        (rows[i]["close"] / prev - 1) * 100))
    return out


def portfolio_backtest(codes: list[str], names: dict[str, str] | None = None,
                       start: str | None = None,
                       end: str | None = None) -> dict:
    """等权组合回测 vs 沪深 300。返回统计 dict。"""
    from .storage import load_klines

    names = names or {}
    # 标的日收益
    series: dict[str, list[tuple[str, float]]] = {}
    for c in codes:
        try:
            rows = load_klines(c, "ashare")
        except Exception:  # noqa: BLE001
            continue
        if len(rows) < 60:
            continue
        series[c] = _daily_returns(rows)
    if len(series) < 2:
        raise RuntimeError("本地 K 线不足（请先 backfill）")

    # 基准沪深 300
    import akshare as ak

    idx = ak.stock_zh_index_daily(symbol="sh000300")
    idx_rows = [{"date": str(r["date"])[:10], "close": float(r["close"])}
                for _, r in idx.iterrows()]
    idx_ret = _daily_returns(idx_rows)
    idx_map = dict(idx_ret)

    # 按日期合并（标的交集 + 基准）
    dates: dict[str, dict[str, float]] = {}
    for c, rets in series.items():
        for d, r in rets:
            dates.setdefault(d, {})[c] = r
    common = [d for d, _ in idx_ret if d in dates]
    if start:
        common = [d for d in common if d >= start]
    if end:
        common = [d for d in common if d <= end]
    if len(common) < 30:
        raise RuntimeError(f"有效交易日过少（{len(common)}），请调整区间")

    # 等权组合日收益 = 各标日收益均值
    port_ret = [sum(dates[d].values()) / len(dates[d]) for d in common]
    bench_ret = [idx_map[d] for d in common]
    dates_use = common

    # 统计
    def _stats(rets: list[float]) -> dict:
        nav = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in rets:
            nav *= (1 + r / 100)
            peak = max(peak, nav)
            max_dd = max(max_dd, (peak - nav) / peak)
        total = (nav - 1) * 100
        n_days = len(rets)
        annual = ((1 + total / 100) ** (365 / n_days) - 1) * 100 if n_days > 0 else 0.0
        mean = sum(rets) / n_days if n_days else 0.0
        var = sum((r - mean) ** 2 for r in rets) / n_days if n_days else 0.0
        sharpe = (mean / (var ** 0.5) * (252 ** 0.5)
                  if var > 0 else 0.0)
        return {"total": round(total, 2), "annual": round(annual, 2),
                "max_dd": round(max_dd * 100, 2), "sharpe": round(sharpe, 2),
                "days": n_days}

    return {
        "codes": codes, "start": dates_use[0], "end": dates_use[-1],
        "portfolio": _stats(port_ret), "benchmark": _stats(bench_ret),
        "excess_annual": round(
            _stats(port_ret)["annual"] - _stats(bench_ret)["annual"], 2),
    }


# ===================== 月度再平衡（差额调仓） =====================

# 目标持仓 vs 当前持仓（paper_positions）→ 差额指令（买入/卖出/清仓）。
# 低频再平衡：月度执行，整手差额，权重漂移修正。


def rebalance_orders(targets: list[TargetPosition],
                     capital: float) -> list[dict]:
    """计算差额指令：目标市值 vs 当前市值（现价×股数）。"""
    from .quotes import fetch_spot_quotes

    pos = {p["code"]: p for p in load_paper_positions()}
    codes = list(dict.fromkeys(list(pos.keys()) + [t.code for t in targets]))
    quotes = {}
    try:
        qs, _ = fetch_spot_quotes(codes, market="ashare")
        quotes = {q.code: q for q in qs}
    except Exception as exc:  # noqa: BLE001
        logger.warning("再平衡行情获取失败: %s", exc)

    target_map = {t.code: t for t in targets}
    orders: list[dict] = []
    for code in codes:
        q = quotes.get(code)
        price = q.price if q else None
        cur = pos.get(code)
        cur_value = (cur["shares"] * price if cur and price else 0.0)
        t = target_map.get(code)
        tgt_value = t.target_value if t else 0.0   # 不在新目标 → 清仓
        diff = tgt_value - cur_value
        if abs(diff) < 500:   # 小额漂移忽略（避免频繁微调）
            continue
        if not price:
            orders.append({"code": code,
                           "name": t.name if t else (cur["name"] if cur else code),
                           "side": "hold", "shares": 0, "reason": "行情缺失"})
            continue
        shares = int(abs(diff) // price // 100) * 100  # 整手
        if shares <= 0:
            continue
        side = "buy" if diff > 0 else "sell"
        orders.append({"code": code,
                       "name": t.name if t else (cur["name"] if cur else code),
                       "side": side, "shares": shares,
                       "price": round(price, 2),
                       "value": round(shares * price, 2),
                       "reason": ("新进" if (t and not cur) else
                                  "清仓" if (cur and not t) else
                                  "加仓" if side == "buy" else "减仓")})
    return orders


def execute_rebalance(orders: list[dict]) -> dict:
    """执行差额指令：买入复用 execute_paper_trade；卖出更新持仓。"""
    import sqlite3

    from .storage import get_conn

    buy_targets = [TargetPosition(o["code"], o["name"],
                                  round(o["value"] / max(sum(
                                      x["value"] for x in orders if x["side"] == "buy"
                                      ), 1) * 100, 2), o["value"])
                   for o in orders if o["side"] == "buy"]
    buy_result = execute_paper_trade(buy_targets) if buy_targets else \
        {"fills": [], "total_cost": 0.0, "rejected": []}

    sells = [o for o in orders if o["side"] == "sell"]
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    sold = []
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT, name TEXT, side TEXT, shares INTEGER,
                price REAL, cost REAL, trade_date TEXT)"""
        )
        for o in sells:
            cur = conn.execute(
                "SELECT * FROM paper_positions WHERE code=?",
                (o["code"],)).fetchone()
            if not cur:
                continue
            remaining = cur["shares"] - o["shares"]
            if remaining <= 0:
                conn.execute("DELETE FROM paper_positions WHERE code=?",
                             (o["code"],))
            else:
                conn.execute(
                    "UPDATE paper_positions SET shares=?, updated=? "
                    "WHERE code=?",
                    (remaining, o["reason"], o["code"]))
            conn.execute(
                "INSERT INTO paper_trades "
                "(code, name, side, shares, price, cost, trade_date) "
                "VALUES (?,?,?,?,?,?,?)",
                (o["code"], o["name"], "sell", o["shares"], o["price"],
                 o["value"], datetime.now().strftime("%Y-%m-%d")))
            sold.append(o)
    return {"buy": buy_result, "sell": sold}
