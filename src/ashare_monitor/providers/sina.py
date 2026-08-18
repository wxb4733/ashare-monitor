"""新浪实时行情源（hq.sinajs.cn）。

解析逻辑改编自 easyquotation.sina.Sina（MIT License，
Copyright (c) 2018 shidenggui，
https://github.com/shidenggui/easyquotation），
在本项目中统一转换为 Quote 数据模型。
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import requests

from ..quotes import Quote
from .base import QuoteProvider

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}

# 名称 + 29 个数值字段 + 日期 + 时间
_DETAIL_RE = re.compile(
    r"(\w{2}\d+)=\"([^\s,]+?)%s%s\";"
    % (r",([\.\d]+)" * 29, r",([-\d:]+)" * 2)
)


class SinaProvider(QuoteProvider):
    """新浪免费实时行情，速度快，适合盘中高频轮询。"""

    name = "sina"
    max_num = 800

    @property
    def _api(self) -> str:
        return f"https://hq.sinajs.cn/rn={int(time.time() * 1000)}&list="

    def fetch(self, codes: list[str]) -> list[Quote]:
        symbols = ",".join(self._with_prefix(codes))
        resp = requests.get(self._api + symbols, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        resp.encoding = "gbk"
        return self.parse(resp.text)

    @staticmethod
    def parse(text: str) -> list[Quote]:
        """解析新浪行情文本为 Quote 列表（独立出来便于测试）。"""
        text = text.replace(" ", "")
        quotes: list[Quote] = []
        for m in _DETAIL_RE.finditer(text):
            f = m.groups()
            symbol, name = f[0], f[1]
            (
                open_, prev_close, now, high, low,
                _buy, _sell, turnover, volume,
            ) = (float(f[i]) for i in range(2, 11))
            date_str, time_str = f[31], f[32]
            try:
                ts = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                ts = datetime.now()
            change = now - prev_close
            change_pct = change / prev_close * 100 if prev_close else 0.0
            quotes.append(
                Quote(
                    code=symbol[-6:],
                    name=name,
                    price=now,
                    change_pct=round(change_pct, 2),
                    change=round(change, 4),
                    volume=turnover / 100,   # 股数 → 手
                    turnover=volume,         # 成交额（元）
                    high=high,
                    low=low,
                    open=open_,
                    prev_close=prev_close,
                    timestamp=ts,
                )
            )
        return quotes
