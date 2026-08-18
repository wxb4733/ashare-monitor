"""腾讯实时行情源（qt.gtimg.cn）。

解析逻辑改编自 easyquotation.tencent.Tencent（MIT License，
Copyright (c) 2018 shidenggui，
https://github.com/shidenggui/easyquotation），
在本项目中统一转换为 Quote 数据模型。
"""

from __future__ import annotations

from datetime import datetime

import requests

from ..quotes import Quote
from .base import QuoteProvider

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}


class TencentProvider(QuoteProvider):
    """腾讯免费实时行情，更新频率较高，亦支持港股。"""

    name = "tencent"
    max_num = 60

    _API = "https://qt.gtimg.cn/q="

    def fetch(self, codes: list[str]) -> list[Quote]:
        symbols = ",".join(self._with_prefix(codes))
        resp = requests.get(self._API + symbols, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        resp.encoding = "gbk"
        return self.parse(resp.text)

    @staticmethod
    def parse(text: str) -> list[Quote]:
        """解析腾讯行情文本为 Quote 列表（独立出来便于测试）。"""
        quotes: list[Quote] = []
        for detail in text.split(";"):
            f = detail.split("~")
            if len(f) <= 49:
                continue
            try:
                ts = datetime.strptime(f[30], "%Y%m%d%H%M%S")
            except ValueError:
                ts = datetime.now()
            quotes.append(
                Quote(
                    code=f[2],
                    name=f[1],
                    price=float(f[3]),
                    prev_close=float(f[4]),
                    open=float(f[5]),
                    volume=int(f[36]),                      # 成交量（手）
                    turnover=float(f[37]) * 10000,          # 成交额（万 → 元）
                    change=float(f[31]),
                    change_pct=float(f[32]),
                    high=float(f[33]),
                    low=float(f[34]),
                    timestamp=ts,
                )
            )
        return quotes
