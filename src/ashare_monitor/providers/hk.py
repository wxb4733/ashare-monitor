"""港股实时行情源（腾讯 sqt.gtimg.cn）。

解析逻辑改编自 easyquotation.hkquote.HKQuote（MIT License，
Copyright (c) 2018 shidenggui，
https://github.com/shidenggui/easyquotation），
在本项目中统一转换为 Quote 数据模型。
"""

from __future__ import annotations

import re
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

_LINE_RE = re.compile(r'v_r_hk(\d+)="(.*?)"')


class TencentHKProvider(QuoteProvider):
    """腾讯港股实时行情。代码为 5 位港股代码，如 00700。"""

    name = "tencent_hk"
    max_num = 60

    _API = "https://sqt.gtimg.cn/utf8/q="

    def fetch(self, codes: list[str]) -> list[Quote]:
        symbols = ",".join(f"r_hk{c[-5:]}" for c in codes)
        resp = requests.get(self._API + symbols, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return self.parse(resp.text)

    @staticmethod
    def parse(text: str) -> list[Quote]:
        """解析腾讯港股行情文本为 Quote 列表（独立出来便于测试）。"""
        quotes: list[Quote] = []
        for m in _LINE_RE.finditer(text):
            code, payload = m.group(1), m.group(2)
            f = payload.split("~")
            if len(f) < 51:
                continue
            try:
                ts = datetime.strptime(f[30], "%Y/%m/%d %H:%M:%S")
            except ValueError:
                ts = datetime.now()
            quotes.append(
                Quote(
                    code=code,
                    name=f[1],
                    price=float(f[3]),
                    prev_close=float(f[4]),
                    open=float(f[5]),
                    volume=float(f[6]),               # 成交量（股）
                    turnover=float(f[37]),            # 成交额（港元）
                    change=float(f[31]),
                    change_pct=float(f[32]),
                    high=float(f[33]),
                    low=float(f[34]),
                    timestamp=ts,
                )
            )
        return quotes
