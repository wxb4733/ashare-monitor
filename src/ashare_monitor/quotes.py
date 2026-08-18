"""行情数据获取模块（基于 akshare 实时行情接口）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import akshare as ak
import pandas as pd


@dataclass
class Quote:
    code: str
    name: str
    price: float          # 最新价
    change_pct: float     # 涨跌幅 %
    change: float         # 涨跌额
    volume: float         # 成交量（手）
    turnover: float       # 成交额（元）
    high: float
    low: float
    open: float
    prev_close: float     # 昨收
    timestamp: datetime


def fetch_spot_quotes(codes: list[str]) -> list[Quote]:
    """获取指定代码的实时行情快照。

    通过 akshare 拉取全市场快照后按代码过滤，减少请求次数。
    """
    df: pd.DataFrame = ak.stock_zh_a_spot_em()
    df["代码"] = df["代码"].astype(str).str[-6:]
    df = df[df["代码"].isin(codes)]

    quotes: list[Quote] = []
    now = datetime.now()
    for _, row in df.iterrows():
        quotes.append(
            Quote(
                code=str(row["代码"]),
                name=str(row["名称"]),
                price=float(row["最新价"]),
                change_pct=float(row["涨跌幅"]),
                change=float(row["涨跌额"]),
                volume=float(row["成交量"]),
                turnover=float(row["成交额"]),
                high=float(row["最高"]),
                low=float(row["最低"]),
                open=float(row["今开"]),
                prev_close=float(row["昨收"]),
                timestamp=now,
            )
        )
    return quotes


def fetch_index_quotes() -> pd.DataFrame:
    """获取主要指数行情（上证、深证、创业板等）。"""
    return ak.stock_zh_index_spot_em()


def is_trading_time(sessions: list[list[str]], now: datetime | None = None) -> bool:
    """判断当前是否处于交易时段（周一至周五且在交易时间段内）。"""
    now = now or datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    current = now.strftime("%H:%M")
    return any(start <= current <= end for start, end in sessions)
