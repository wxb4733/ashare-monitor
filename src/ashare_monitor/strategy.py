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


# ===================== 风控层（低频交易生命线） =====================

# 规则：单标的上限 / ST 退市黑名单 / 最小市值过滤。
# 风控优先于策略：目标持仓与再平衡指令先过风控再执行。


def apply_risk_rules(targets: list[TargetPosition],
                     max_weight: float = 20.0,
                     min_market_cap: float | None = 20.0,
                     exclude_st: bool = True) -> dict:
    """对目标持仓应用风控规则。返回 {accepted, rejected, notes}。

    :param max_weight: 单标的最大权重 %（默认 20）
    :param min_market_cap: 最小市值（亿），None 不启用
    """
    accepted, rejected = [], []
    notes = []
    for t in targets:
        # ST/退市黑名单（名称启发式）
        if exclude_st and ("ST" in t.name.upper() or "退" in t.name):
            rejected.append({"code": t.code, "name": t.name,
                             "reason": "ST/退市黑名单"})
            continue
        # 单标的上限
        if t.weight > max_weight:
            notes.append(f"{t.name} 权重 {t.weight:.0f}% > 上限 {max_weight:.0f}%"
                         f"（调降至上限）")
            t = TargetPosition(t.code, t.name, max_weight,
                               round(t.target_value, 2))
        # 最小市值（东财行情市值，沙箱可能不可达 → 跳过如实）
        if min_market_cap is not None:
            mv = _try_market_cap(t.code)
            if mv is None:
                notes.append(f"{t.name} 市值数据不可得（风控跳过市值检查）")
            elif mv < min_market_cap:
                rejected.append({"code": t.code, "name": t.name,
                                 "reason": f"市值 {mv:.0f} 亿 < {min_market_cap:.0f} 亿"})
                continue
        accepted.append(t)
    return {"accepted": accepted, "rejected": rejected, "notes": notes}


def _try_market_cap(code: str) -> float | None:
    """尝试取市值（亿）。东财行情接口不可用时返回 None。"""
    try:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return None
        row = df[df["代码"] == code]
        if len(row):
            return float(row.iloc[0].get("总市值", 0)) / 1e8
    except Exception:  # noqa: BLE001
        pass
    return None


# ===================== 模拟持仓报告（跟踪） =====================

def paper_report() -> dict:
    """模拟持仓市值/盈亏报告（现价×股数 vs 成本）。"""
    from .quotes import fetch_spot_quotes

    pos = load_paper_positions()
    if not pos:
        return {"positions": [], "total_cost": 0.0, "total_value": 0.0,
                "pnl": 0.0, "pnl_pct": 0.0}
    quotes = {}
    try:
        qs, _ = fetch_spot_quotes([p["code"] for p in pos], market="ashare")
        quotes = {q.code: q for q in qs}
    except Exception as exc:  # noqa: BLE001
        logger.warning("持仓报告行情失败: %s", exc)
    rows = []
    total_cost = total_value = 0.0
    for p in pos:
        q = quotes.get(p["code"])
        price = q.price if q else None
        cost = p["shares"] * p["avg_cost"]
        value = p["shares"] * price if price else None
        rows.append({"code": p["code"], "name": p["name"],
                     "shares": p["shares"], "avg_cost": p["avg_cost"],
                     "price": price, "cost": round(cost, 2),
                     "value": round(value, 2) if value else None,
                     "pnl_pct": round((value / cost - 1) * 100, 2)
                     if value and cost else None})
        total_cost += cost
        if value:
            total_value += value
    return {"positions": rows, "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "pnl": round(total_value - total_cost, 2),
            "pnl_pct": round((total_value / total_cost - 1) * 100, 2)
            if total_cost else 0.0}


# ===================== 止损风控（单标的止损检查） =====================

def stop_loss_check(stop_pct: float = 15.0) -> dict:
    """检查模拟持仓止损：现价 vs 成本，亏损 > stop_pct 标记止损卖出建议。"""
    from .quotes import fetch_spot_quotes

    pos = load_paper_positions()
    if not pos:
        return {"triggers": [], "total": 0}
    quotes = {}
    try:
        qs, _ = fetch_spot_quotes([p["code"] for p in pos], market="ashare")
        quotes = {q.code: q for q in qs}
    except Exception as exc:  # noqa: BLE001
        logger.warning("止损检查行情失败: %s", exc)
    triggers = []
    for p in pos:
        q = quotes.get(p["code"])
        if not q or not q.price:
            continue
        loss = (q.price / p["avg_cost"] - 1) * 100
        if loss <= -stop_pct:
            triggers.append({"code": p["code"], "name": p["name"],
                             "shares": p["shares"], "cost": p["avg_cost"],
                             "price": q.price, "loss_pct": round(loss, 2)})
    triggers.sort(key=lambda x: x["loss_pct"])
    return {"triggers": triggers, "total": len(pos)}


# ===================== 月度换仓回测（动态再平衡） =====================

# 与静态等权回测对比：每月末按等权重新平衡（模拟真实月度调仓）。
# 静态：买入持有；动态：每月再平衡一次（跟踪误差/超额对比）。


def portfolio_backtest_rebalanced(codes: list[str],
                                  start: str | None = None,
                                  end: str | None = None,
                                  frequency: str = "monthly",
                                  cost_bps: float = 5.0) -> dict:
    """再平衡回测（频率可调 + 交易成本）vs 静态等权 vs 沪深 300。

    :param frequency: monthly / quarterly / semi_annual 再平衡周期
    :param cost_bps: 单边综合交易成本（bp，含佣金+印花税+滑点，默认 5bp=0.05%）
    """
    from .storage import load_klines

    series: dict[str, list[dict]] = {}
    for c in codes:
        try:
            rows = load_klines(c, "ashare")
        except Exception:  # noqa: BLE001
            continue
        if len(rows) < 60:
            continue
        series[c] = rows
    if len(series) < 2:
        raise RuntimeError("本地 K 线不足（请先 backfill）")

    import akshare as ak

    idx = ak.stock_zh_index_daily(symbol="sh000300")
    idx_rows = [{"date": str(r["date"])[:10], "close": float(r["close"])}
                for _, r in idx.iterrows()]
    idx_map = {r["date"]: r["close"] for r in idx_rows}

    # 按日期合并所有标的收盘
    dates = sorted({r["date"] for rows in series.values() for r in rows})
    if start:
        dates = [d for d in dates if d >= start]
    if end:
        dates = [d for d in dates if d <= end]
    # 只保留所有标的有数据的日期（上市时间差对齐）
    close_at = {}
    for d in dates:
        vals = {c: _close_on(series[c], d) for c in series}
        if all(v is not None for v in vals.values()):
            close_at[d] = vals
    dates = [d for d in dates if d in close_at]

    # 静态等权：买入持有
    def _buy_hold():
        first = close_at[dates[0]]
        units = {c: 1.0 / first[c] if first[c] else 0.0 for c in series}
        nav = 1.0
        navs = []
        for d in dates:
            val = sum(units[c] * close_at[d][c] for c in series)
            nav = val / sum(units[c] * first[c] for c in series)
            navs.append((nav - 1) * 100)
        return _ret_stats(navs, dates)

    # 周期再平衡：周期首日重置等权，按 cost_bps 扣除换仓成本
    def _periodic():
        nav = 1.0
        navs = []
        cur_key = None
        last_val = {c: close_at[dates[0]][c] for c in series}
        for d in dates:
            key = _period_key(d, frequency)
            if cur_key is None or key != cur_key:
                cur_key = key
                # 周期首日等权重置 + 扣换仓成本（按当时组合市值）
                last_val = {c: close_at[d][c] for c in series}
                nav *= (1 - cost_bps / 10000)
            day_ret = sum((close_at[d][c] / last_val[c] - 1)
                          for c in series if last_val[c]) / len(series)
            nav *= (1 + day_ret)
            last_val = {c: close_at[d][c] for c in series}
            navs.append((nav - 1) * 100)
        return _ret_stats(navs, dates)

    def _buy_hold_cost():
        # 静态等权：仅首日建仓成本
        first = close_at[dates[0]]
        units = {c: 1.0 / first[c] if first[c] else 0.0 for c in series}
        nav = 1.0 - cost_bps / 10000
        navs = []
        for d in dates:
            val = sum(units[c] * close_at[d][c] for c in series)
            nav = (1 - cost_bps / 10000) * val / sum(
                units[c] * first[c] for c in series)
            navs.append((nav - 1) * 100)
        return _ret_stats(navs, dates)

    # 基准
    bench_nav = []
    base = idx_map.get(dates[0])
    if base:
        for d in dates:
            v = idx_map.get(d)
            if v:
                bench_nav.append((v / base - 1) * 100)

    def _bench_stats():
        nav = 1.0
        navs = []
        prev = None
        for d in dates:
            v = idx_map.get(d)
            if v and prev:
                nav *= (1 + (v / prev - 1))
            if v:
                prev = v
                navs.append((nav - 1) * 100)
        return _ret_stats(navs, dates)

    return {
        "dates": dates,
        "buy_hold": _buy_hold(),
        "buy_hold_cost": _buy_hold_cost(),
        "periodic": _periodic(),
        "frequency": frequency, "cost_bps": cost_bps,
        "benchmark": _bench_stats(),
    }


def _period_key(date: str, frequency: str) -> str:
    """再平衡周期键（月/季/半年）。"""
    y, m = date[:4], int(date[5:7])
    if frequency == "quarterly":
        return f"{y}Q{(m - 1) // 3 + 1}"
    if frequency == "semi_annual":
        return f"{y}S{(m - 1) // 6 + 1}"
    return f"{y}-{m:02d}"   # monthly


def _close_on(rows: list[dict], date: str) -> float | None:
    for r in rows:
        if r["date"] == date:
            return float(r["close"])
    return None


def _ret_stats(nav_pcts: list[float], dates: list[str]) -> dict:
    """从累计收益序列算统计。"""
    nav = 1.0
    peak = 1.0
    max_dd = 0.0
    rets = []
    prev = 1.0
    for pct in nav_pcts:
        cur = 1 + pct / 100
        rets.append((cur / prev - 1) * 100)
        prev = cur
        nav = cur
        peak = max(peak, nav)
        max_dd = max(max_dd, (peak - nav) / peak)
    total = (nav - 1) * 100
    n = len(nav_pcts)
    annual = ((1 + total / 100) ** (365 / n) - 1) * 100 if n > 0 else 0.0
    mean = sum(rets) / n if n else 0.0
    var = sum((r - mean) ** 2 for r in rets) / n if n else 0.0
    sharpe = (mean / (var ** 0.5) * (252 ** 0.5) if var > 0 else 0.0)
    return {"total": round(total, 2), "annual": round(annual, 2),
            "max_dd": round(max_dd * 100, 2), "sharpe": round(sharpe, 2),
            "days": n}


# ===================== 模拟净值跟踪 + 组合熔断 =====================

def record_paper_nav() -> dict:
    """记录今日模拟组合净值（总市值/成本/累计收益%）到 paper_history。"""
    import sqlite3

    from .storage import get_conn

    rep = paper_report()
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS paper_history (
                date TEXT PRIMARY KEY, value REAL, cost REAL,
                nav REAL, pnl_pct REAL)"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO paper_history (date, value, cost, nav, pnl_pct) "
            "VALUES (?,?,?,?,?)",
            (today, rep["total_value"], rep["total_cost"],
             rep["total_value"] / rep["total_cost"]
             if rep["total_cost"] else 1.0, rep["pnl_pct"]))
    return {"date": today, **rep}


def load_paper_nav() -> list[dict]:
    """读取净值历史（升序）。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM paper_history ORDER BY date").fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


def portfolio_circuit_breaker(drawdown_pct: float = 20.0) -> dict:
    """组合级熔断：现价市值 vs 成本亏损 > 阈值 → 停止新开仓。"""
    rep = paper_report()
    loss = -rep["pnl_pct"] if rep["pnl_pct"] < 0 else 0.0
    triggered = loss >= drawdown_pct
    return {"triggered": triggered, "loss_pct": round(loss, 2),
            "threshold": drawdown_pct,
            "total_value": rep["total_value"], "total_cost": rep["total_cost"]}
