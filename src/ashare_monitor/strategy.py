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
                        dry_run: bool = False,
                        cash: float | None = None,
                        commission_bps: float = 0.0,
                        stamp_duty_bps: float = 0.0) -> dict:
    """按现价模拟买入（整手），走 PaperBroker（现金账户 + 订单状态机）。

    :param cash: 注入资金（None=保留账户现金；旧账户无现金记录时给宽松额度）
    :param commission_bps: 佣金（万分比，A 股参考 2.5=万 2.5）
    :param stamp_duty_bps: 印花税（卖出，万分比，A 股参考 5=0.05%）
    :return: {"fills": [...], "total_cost": float, "rejected": [...],
              "cash": float}
    """
    import sqlite3

    from .broker import PaperBroker
    from .quotes import fetch_spot_quotes
    from .storage import get_conn

    codes = [t.code for t in targets]
    quotes = {}
    try:
        qs, src = fetch_spot_quotes(codes, market="ashare")
        quotes = {q.code: q for q in qs}
    except Exception as exc:  # noqa: BLE001
        logger.warning("行情获取失败: %s", exc)

    broker = PaperBroker.load()
    broker.commission_bps = commission_bps
    broker.stamp_duty_bps = stamp_duty_bps
    if cash is not None:
        broker.cash += cash                        # 注入资金（追加）
    elif broker.cash <= 0:
        broker.cash = 1_000_000.0                  # 旧账户无现金记录 → 宽松额度（如实）

    for t in targets:
        q = quotes.get(t.code)
        if q is None or not q.price:
            broker.place_order(t.code, t.name, "buy", 0, 0.0,
                               reason="行情缺失")
            continue
        shares = int(t.target_value // q.price // 100) * 100  # 整手
        if shares <= 0:
            broker.place_order(t.code, t.name, "buy", 0, 0.0,
                               reason=f"资金不足一手（价 {q.price:.2f}）")
            continue
        reason = "新进" if not broker.positions.get(t.code) else "加仓"
        broker.place_order(t.code, t.name, "buy", shares, q.price,
                           reason=reason)
    processed = broker.process_orders()

    fills, rejected = [], []
    for o in processed:
        if o["status"] == "Filled":
            fills.append({"code": o["code"], "name": o["name"],
                          "shares": o["shares"], "price": o["price"],
                          "cost": round(o["shares"] * o["price"], 2),
                          "fee": o["fee"],
                          "date": datetime.now().strftime("%Y-%m-%d")})
        else:
            rejected.append({"code": o["code"], "name": o["name"],
                             "reason": o["reason"] or "资金不足"})
    total = sum(f["cost"] for f in fills)
    if not dry_run:
        broker.save()
        conn = get_conn()
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT, name TEXT, side TEXT, shares INTEGER,
                    price REAL, cost REAL, trade_date TEXT)"""
            )
            for f in fills:
                conn.execute(
                    "INSERT INTO paper_trades "
                    "(code, name, side, shares, price, cost, trade_date) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (f["code"], f["name"], "buy", f["shares"], f["price"],
                     f["cost"], f["date"]))
    return {"fills": fills, "total_cost": round(total, 2),
            "rejected": rejected, "cash": round(broker.cash, 2)}
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


def execute_rebalance(orders: list[dict], cash: float | None = None,
                      commission_bps: float = 0.0,
                      stamp_duty_bps: float = 0.0) -> dict:
    """执行差额指令（走 PaperBroker：买/卖统一订单状态机 + 现金账户）。"""
    import sqlite3

    from .broker import PaperBroker
    from .storage import get_conn

    broker = PaperBroker.load()
    broker.commission_bps = commission_bps
    broker.stamp_duty_bps = stamp_duty_bps
    if cash is not None:
        broker.cash += cash
    elif broker.cash <= 0:
        broker.cash = 1_000_000.0                  # 旧账户无现金记录 → 宽松额度

    for o in orders:
        if o["side"] == "hold":
            continue
        broker.place_order(o["code"], o["name"], o["side"], o["shares"],
                           o["price"], reason=o["reason"])
    processed = broker.process_orders()
    broker.save()

    buys, sells = [], []
    for o in processed:
        if o["status"] != "Filled":
            continue
        rec = {"code": o["code"], "name": o["name"], "side": o["side"],
               "shares": o["shares"], "price": o["price"],
               "value": round(o["shares"] * o["price"], 2),
               "fee": o["fee"], "reason": o["reason"]}
        (buys if o["side"] == "buy" else sells).append(rec)
    # 交易日志（兼容 paper_trades）
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT, name TEXT, side TEXT, shares INTEGER,
                price REAL, cost REAL, trade_date TEXT)"""
        )
        for o in processed:
            if o["status"] != "Filled":
                continue
            conn.execute(
                "INSERT INTO paper_trades "
                "(code, name, side, shares, price, cost, trade_date) "
                "VALUES (?,?,?,?,?,?,?)",
                (o["code"], o["name"], o["side"], o["shares"], o["price"],
                 round(o["shares"] * o["price"], 2),
                 datetime.now().strftime("%Y-%m-%d")))
    buy_result = {"fills": buys,
                  "total_cost": round(sum(b["value"] for b in buys), 2),
                  "rejected": [o for o in processed
                               if o["status"] == "Rejected"]}
    return {"buy": buy_result, "sell": sells,
            "cash": round(broker.cash, 2)}
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

    from .broker import PaperBroker

    pos = load_paper_positions()
    broker = PaperBroker.load()
    if not pos:
        return {"positions": [], "total_cost": 0.0, "total_value": 0.0,
                "pnl": 0.0, "pnl_pct": 0.0, "cash": round(broker.cash, 2),
                "equity": round(broker.cash, 2)}
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
            if total_cost else 0.0,
            "cash": round(broker.cash, 2),
            "equity": round(broker.cash + total_value, 2)}


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
                                  cost_bps: float = 5.0,
                                  limit_pct: float | None = 9.5) -> dict:
    """再平衡回测（频率可调 + 交易成本 + A 股交易规则）vs 静态等权 vs 沪深 300。

    :param frequency: monthly / quarterly / semi_annual 再平衡周期
    :param cost_bps: 单边综合交易成本（bp，含佣金+印花税+滑点，默认 5bp=0.05%）
    :param limit_pct: 涨跌停成交约束阈值 %（涨幅 ≥ 阈值=涨停日买入受限，
                      跌幅 ≤ -阈值=跌停日卖出受限；None 关闭）。
                      主板 10% / 创业科创 20% 用近似 9.5%（排除普通大阳线）。
    A 股规则说明：T+1 对低频月度/季度再平衡无实际影响（周期首日卖出的都是
    上一周期已持有 ≥1 天的仓位，天然满足 T+1）——如实标注；涨跌停约束才是
    实际影响项（一字涨停买不进/一字跌停卖不出）。
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

    # 指数缓存（网格优化多轮复用，避免重复拉取）
    cache_key = (start, end)
    if cache_key not in _INDEX_CACHE:
        idx = ak.stock_zh_index_daily(symbol="sh000300")
        idx_rows = [{"date": str(r["date"])[:10], "close": float(r["close"])}
                    for _, r in idx.iterrows()]
        _INDEX_CACHE[cache_key] = {r["date"]: r["close"] for r in idx_rows}
    idx_map = _INDEX_CACHE[cache_key]

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
        return _ret_stats(navs, dates), navs

    # 周期再平衡：周期首日重置等权（涨跌停受限标的不重置），扣换仓成本
    def _periodic():
        nav = 1.0
        navs = []
        cur_key = None
        last_val = {c: close_at[dates[0]][c] for c in series}
        prev_closes = {c: close_at[dates[0]][c] for c in series}
        for i, d in enumerate(dates):
            key = _period_key(d, frequency)
            if cur_key is None or key != cur_key:
                cur_key = key
                # 涨跌停约束判断（用当日涨跌幅近似）
                buy_blocked, sell_blocked = set(), set()
                if limit_pct is not None and i > 0:
                    for c in series:
                        pc = close_at[dates[i - 1]][c]
                        if pc:
                            chg = (close_at[d][c] / pc - 1) * 100
                            if chg >= limit_pct:
                                buy_blocked.add(c)      # 涨停日买入受限
                            elif chg <= -limit_pct:
                                sell_blocked.add(c)     # 跌停日卖出受限
                # 未受限标的重置等权；受限标的保留旧权重（如实模拟成交约束）
                new_val = {}
                for c in series:
                    if c in buy_blocked or c in sell_blocked:
                        new_val[c] = last_val[c]
                    else:
                        new_val[c] = close_at[d][c]
                last_val = new_val
                nav *= (1 - cost_bps / 10000)
            day_ret = sum((close_at[d][c] / last_val[c] - 1)
                          for c in series if last_val[c]) / len(series)
            nav *= (1 + day_ret)
            prev_closes = {c: close_at[d][c] for c in series}
            last_val = {c: close_at[d][c] for c in series}
            navs.append((nav - 1) * 100)
        return _ret_stats(navs, dates), navs

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
        return _ret_stats(navs, dates), navs

    def _bench_stats():
        # 基准净值序列与 dates 对齐（缺失日沿用前值）
        nav = 1.0
        navs = []
        prev = None
        for d in dates:
            v = idx_map.get(d)
            if v:
                if prev:
                    nav *= (1 + (v / prev - 1))
                prev = v
            navs.append((nav - 1) * 100)
        return _ret_stats(navs, dates), navs

    bh_stats, bh_navs = _buy_hold()
    bhc_stats, bhc_navs = _buy_hold_cost()
    per_stats, per_navs = _periodic()
    bench_stats, bench_navs = _bench_stats()
    return {
        "dates": dates,
        "buy_hold": bh_stats,
        "buy_hold_cost": bhc_stats,
        "periodic": per_stats,
        "frequency": frequency, "cost_bps": cost_bps,
        "limit_pct": limit_pct,
        "benchmark": bench_stats,
        "nav_series": {"dates": dates, "buy_hold": bh_navs,
                       "periodic": per_navs, "benchmark": bench_navs},
    }


# 指数缓存（模块级，网格优化复用）
_INDEX_CACHE: dict = {}


def optimize_backtest(codes: list[str],
                      frequencies=("monthly", "quarterly", "semi_annual"),
                      costs=(0.0, 5.0, 10.0),
                      start: str | None = None,
                      limit_pct: float | None = 9.5) -> dict:
    """参数网格优化（backtesting.py optimize 模式）：频率 × 成本 扫描。

    返回 {"results": [...], "best": {...}}——best 按夏普最高，
    results 每项含 frequency/cost_bps/annual/total/max_dd/sharpe/sortino。
    """
    rows = []
    for f in frequencies:
        for c in costs:
            try:
                r = portfolio_backtest_rebalanced(
                    codes, start=start, frequency=f, cost_bps=c,
                    limit_pct=limit_pct)
                rows.append({
                    "frequency": f, "cost_bps": c,
                    "annual": r["periodic"]["annual"],
                    "total": r["periodic"]["total"],
                    "max_dd": r["periodic"]["max_dd"],
                    "sharpe": r["periodic"]["sharpe"],
                    "sortino": r["periodic"]["sortino"],
                    "win_rate": r["periodic"]["win_rate"],
                })
            except Exception as exc:  # noqa: BLE001
                rows.append({"frequency": f, "cost_bps": c,
                             "error": str(exc)[:40]})
    ok = [r for r in rows if "error" not in r]
    best = max(ok, key=lambda r: r["sharpe"]) if ok else None
    return {"results": rows, "best": best}


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
    """从累计收益序列算统计（pyfolio 口径扩展：9 项）。

    新增（相对旧 4 项）：sortino（下行风险调整）/ win_rate（日胜率）/
    profit_factor（盈亏比）/ best_day / worst_day。
    """
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
    # pyfolio 扩展：下行风险 / 胜率 / 盈亏比 / 最佳最差日
    downside_var = sum(r * r for r in rets if r < 0) / n if n else 0.0
    sortino = (mean / (downside_var ** 0.5) * (252 ** 0.5)
               if downside_var > 0 else 0.0)
    win_rate = (sum(1 for r in rets if r > 0) / n * 100 if n else 0.0)
    gains = sum(r for r in rets if r > 0)
    losses = -sum(r for r in rets if r < 0)
    profit_factor = (gains / losses if losses > 0
                     else (99.0 if gains > 0 else 0.0))
    return {"total": round(total, 2), "annual": round(annual, 2),
            "max_dd": round(max_dd * 100, 2), "sharpe": round(sharpe, 2),
            "sortino": round(sortino, 2), "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "best_day": round(max(rets), 2) if rets else 0.0,
            "worst_day": round(min(rets), 2) if rets else 0.0,
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


# ===================== 因子有效性检验（IC/IR/分层/多空） =====================

# 同类项目对比优化（stock-panel 亮点）：选股前先验因子有效性。
# IC（信息系数）：因子排名 vs 未来收益排名 的 Spearman 相关（每日截面）
# IC_IR：IC 均值 / IC 标准差（因子稳定性）
# 分层收益：按因子值 5 分位 → 各层未来收益 → 单调性检验
# 多空组合：Q5(多头) - Q1(空头) 累计收益


def _spearman(x: list[float], y: list[float]) -> float:
    """Spearman 秩相关系数（并列值取平均秩）。"""
    def _rank(v: list[float]) -> list[float]:
        idx = sorted(range(len(v)), key=lambda i: v[i])
        ranks = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[idx[k]] = avg
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    n = len(x)
    if n < 3:
        return 0.0
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    sx = (sum((r - mx) ** 2 for r in rx) ** 0.5)
    sy = (sum((r - my) ** 2 for r in ry) ** 0.5)
    return cov / (sx * sy) if sx and sy else 0.0


# 因子函数统一来自表达式 DSL（factor_dsl）——内置 + factors.local.yaml 可覆盖。
# 兼容层：FACTOR_FNS 保留名字 → fn 映射（内部即 DSL 求值），
# 自定义因子走 get_factor_fn（yaml 或 --expr）。
from .factor_dsl import BUILTIN_EXPRS, eval_factor_expr

FACTOR_FNS = {
    name: (lambda rows, e=e: eval_factor_expr(e, rows))
    for name, e in BUILTIN_EXPRS.items()
}


def factor_ic_test(codes: list[str], factor: str = "momentum",
                   forward_days: int = 20) -> dict:
    """因子 IC 检验：每日截面 Spearman（因子排名 vs 未来收益排名）。

    :return: mean_ic / ic_ir / ic_positive_pct / n_days / samples
    """
    from .storage import load_klines

    if factor in FACTOR_FNS:
        fn = FACTOR_FNS[factor]
    else:
        from .factor_dsl import get_factor_fn

        _, fn = get_factor_fn(factor)   # yaml 自定义 / 直接表达式
    # 面板：每个标的的 {date: factor_value} 与 {date: close}
    fvals: dict[str, dict[str, float]] = {}
    closes: dict[str, dict[str, float]] = {}
    for c in codes:
        try:
            rows = load_klines(c, "ashare")
        except Exception:  # noqa: BLE001
            continue
        if len(rows) < 80:
            continue
        fvals[c] = fn(rows)
        closes[c] = {r["date"]: float(r["close"]) for r in rows}
    if len(fvals) < 2:
        raise RuntimeError("本地 K 线不足（至少 2 只标的）")

    # 所有日期并集（升序）
    dates = sorted({d for v in fvals.values() for d in v})
    ics = []
    for d in dates:
        # 未来 forward 天收益（用每个标的下一个可用 close）
        fv, fwd = [], []
        for c in codes:
            if c not in fvals or d not in fvals[c]:
                continue
            v = fvals[c][d]
            # 未来收益：d 之后 forward_days 天的收益（取 d+forward 的 close）
            later = [dd for dd in closes[c] if dd > d]
            if len(later) < forward_days:
                continue
            target = later[min(forward_days - 1, len(later) - 1)]
            ret = (closes[c][target] / closes[c][d] - 1) * 100
            fv.append(v)
            fwd.append(ret)
        if len(fv) >= 3 and len(set(fv)) > 1:
            ics.append(_spearman(fv, fwd))
    if not ics:
        return {"mean_ic": 0.0, "ic_ir": 0.0, "ic_positive_pct": 0.0,
                "n_days": 0, "samples": 0}
    mean_ic = sum(ics) / len(ics)
    var = sum((x - mean_ic) ** 2 for x in ics) / len(ics)
    ic_ir = mean_ic / (var ** 0.5) if var > 0 else 0.0
    pos = sum(1 for x in ics if x > 0) / len(ics) * 100
    return {"mean_ic": round(mean_ic, 4), "ic_ir": round(ic_ir, 3),
            "ic_positive_pct": round(pos, 1), "n_days": len(ics),
            "samples": sum(len(fv) for fv in []) or len(ics)}


def factor_quantile_test(codes: list[str], factor: str = "momentum",
                         quantiles: int = 5, forward_days: int = 20) -> dict:
    """因子分层检验：按因子值 5 分位 → 各层未来收益 → 单调性 + 多空。"""
    from .storage import load_klines

    if factor in FACTOR_FNS:
        fn = FACTOR_FNS[factor]
    else:
        from .factor_dsl import get_factor_fn

        _, fn = get_factor_fn(factor)
    closes: dict[str, dict[str, float]] = {}
    fvals: dict[str, dict[str, float]] = {}
    for c in codes:
        try:
            rows = load_klines(c, "ashare")
        except Exception:  # noqa: BLE001
            continue
        if len(rows) < 80:
            continue
        closes[c] = {r["date"]: float(r["close"]) for r in rows}
        fvals[c] = fn(rows)
    # 收集所有 (因子值, 未来收益) 样本
    samples = []
    for c in fvals:
        for d, v in fvals[c].items():
            later = [dd for dd in closes[c] if dd > d]
            if len(later) < forward_days:
                continue
            target = later[min(forward_days - 1, len(later) - 1)]
            ret = (closes[c][target] / closes[c][d] - 1) * 100
            samples.append((v, ret))
    if len(samples) < quantiles * 5:
        return {"quantiles": [], "monotonic": False,
                "samples": len(samples), "note": "样本不足"}
    samples.sort(key=lambda x: x[0])
    n = len(samples)
    size = n // quantiles
    layers = []
    for q in range(quantiles):
        seg = samples[q * size: (q + 1) * size if q < quantiles - 1 else n]
        if not seg:
            continue
        avg_ret = sum(x[1] for x in seg) / len(seg)
        layers.append({"quantile": q + 1,
                       "factor_range": f"{seg[0][0]:.2f}~{seg[-1][0]:.2f}",
                       "avg_ret": round(avg_ret, 2), "n": len(seg)})
    if len(layers) < 2:
        return {"quantiles": [], "monotonic": False, "samples": len(samples)}
    # 单调性：Q5 > Q4 > Q3 > Q2 > Q1（严格递减为反向有效）
    rets = [l["avg_ret"] for l in layers]
    ascending = all(rets[i] <= rets[i + 1] for i in range(len(rets) - 1))
    descending = all(rets[i] >= rets[i + 1] for i in range(len(rets) - 1))
    spread = rets[-1] - rets[0]
    return {"quantiles": layers, "monotonic": ascending or descending,
            "long_short": round(spread, 2), "samples": len(samples)}
