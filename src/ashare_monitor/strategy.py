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
