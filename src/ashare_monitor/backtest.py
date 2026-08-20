"""持有期回测：某日买入一定金额，持有 N 个交易日后卖出，计算收益率。

数据源：优先使用已回填入库的日 K（klines 表，离线快速）；
未回填时自动现拉日线兜底（不入库）。

注意：按整手成交（A 股 100 股/手、港股按每手股数），未计佣金/税费，
结果仅为历史价格模拟，不构成投资建议。
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 默认每手股数（A 股 100；港股不同标的不同，比亚迪 01211 为 500）
_DEFAULT_LOT = {"ashare": 100, "hk": 500}


def _load_daily(code: str, market: str) -> list[dict]:
    """取日 K 序列（优先入库数据，缺失时现拉）。"""
    from .storage import load_klines

    rows = load_klines(code, market)
    if len(rows) >= 2:
        return rows
    logger.info("%s(%s) 库内无日 K，现拉日线兜底", code, market)
    from .analysis import fetch_history

    df, _ = fetch_history(code, days=300, adjust="qfq",
                          market=market, period="daily")
    return [
        {"date": str(r["日期"])[:10], "open": float(r["开盘"]),
         "close": float(r["收盘"]), "high": float(r["最高"]),
         "low": float(r["最低"]), "volume": float(r["成交量"])}
        for _, r in df.iterrows()
    ]


def backtest(
    code: str,
    market: str = "ashare",
    buy_date: str | None = None,
    amount: float = 100000.0,
    hold_days: list[int] | None = None,
    lot_size: int | None = None,
    rows: list[dict] | None = None,
) -> list[dict]:
    """执行持有期回测。

    :param rows: 日 K 序列（测试可注入），None 时按 code/market 获取
    :return: 每档持有期的回测结果 dict 列表
    """
    rows = rows if rows is not None else _load_daily(code, market)
    if len(rows) < 2:
        raise RuntimeError(f"{code} 日 K 数据不足（{len(rows)} 根）")

    lot = lot_size or _DEFAULT_LOT.get(market, 100)
    holds = hold_days or [60]

    # 买入日：首个日期 >= buy_date 的交易日；未指定取最后一天之前（保证有数据可卖）
    buy_date = buy_date or rows[-2]["date"]
    buy_idx = next(
        (i for i, r in enumerate(rows) if r["date"] >= buy_date),
        len(rows) - 2,
    )
    buy = rows[buy_idx]

    results = []
    for hd in sorted(holds):
        sell_idx = buy_idx + hd
        if sell_idx >= len(rows):
            results.append({
                "hold_days": hd, "status": "数据不足",
                "available": len(rows) - 1 - buy_idx,
                "buy_date": buy["date"], "buy_price": buy["close"],
            })
            continue
        sell = rows[sell_idx]

        shares = int(amount / buy["close"] / lot) * lot
        if shares <= 0:
            results.append({
                "hold_days": hd, "status": "金额不足一手",
                "buy_date": buy["date"], "buy_price": buy["close"],
                "lot": lot,
            })
            continue
        buy_amount = shares * buy["close"]
        sell_amount = shares * sell["close"]

        # 持有期最高/最低（含买入与卖出日）
        window = rows[buy_idx:sell_idx + 1]
        high = max(r["high"] for r in window)
        low = min(r["low"] for r in window)

        days_held = sell_idx - buy_idx
        span_days = (
            datetime.strptime(sell["date"], "%Y-%m-%d")
            - datetime.strptime(buy["date"], "%Y-%m-%d")
        ).days
        ret = (sell_amount / buy_amount - 1) * 100
        annualized = (
            ((sell_amount / buy_amount) ** (365 / span_days) - 1) * 100
            if span_days > 0 else 0.0
        )

        results.append({
            "hold_days": days_held,
            "status": "ok",
            "buy_date": buy["date"], "buy_price": buy["close"],
            "sell_date": sell["date"], "sell_price": sell["close"],
            "shares": shares, "lot": lot,
            "buy_amount": buy_amount, "sell_amount": sell_amount,
            "return_pct": round(ret, 2),
            "annualized_pct": round(annualized, 2),
            "high": high, "low": low,
            "span_days": span_days,
        })
    return results
