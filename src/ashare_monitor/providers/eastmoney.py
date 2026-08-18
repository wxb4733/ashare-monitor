"""东方财富行情源（基于 akshare 全市场快照）。

字段最全（含换手率、市值等扩展数据），但每次拉取全市场快照，
开销大于新浪/腾讯的按需查询，适合作为兜底数据源。
"""

from __future__ import annotations

from datetime import datetime

from ..quotes import Quote
from .base import QuoteProvider


class EastMoneyProvider(QuoteProvider):
    """东方财富实时行情快照。"""

    name = "eastmoney"

    def fetch(self, codes: list[str]) -> list[Quote]:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        df["代码"] = df["代码"].astype(str).str[-6:]
        df = df[df["代码"].isin([c[-6:] for c in codes])]

        now = datetime.now()
        quotes: list[Quote] = []
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
