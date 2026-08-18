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

from ..quotes import DepthLevel, Quote
from .base import QuoteProvider

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}

# 提取代码与整个记录（字段数随新浪升级变化，改用分隔符解析而非严格正则）
_LINE_RE = re.compile(r'(\w{2}\d+)="([^"]*)"')

# 报文固定位置（索引从 0 计，忽略末尾新增字段）
_IDX = {
    "name": 0,
    "open": 1, "prev_close": 2, "now": 3, "high": 4, "low": 5,
    "buy": 6, "sell": 7, "turnover": 8, "volume": 9,
    "date": 30, "time": 31,
}


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
        """解析新浪行情文本为 Quote 列表（独立出来便于测试）。

        兼容新浪 32/33/34 字段等不同版本报文：只取固定位置的字段，
        尾部新增字段（如涨速、盘口）一律忽略。
        """
        text = text.replace(" ", "")
        quotes: list[Quote] = []
        for m in _LINE_RE.finditer(text):
            symbol, payload = m.group(1), m.group(2)
            if not payload:
                continue
            f = payload.split(",")
            if len(f) < 33:
                continue
            name = f[_IDX["name"]]
            try:
                open_ = float(f[_IDX["open"]])
                prev_close = float(f[_IDX["prev_close"]])
                now = float(f[_IDX["now"]])
                high = float(f[_IDX["high"]])
                low = float(f[_IDX["low"]])
                turnover = float(f[_IDX["turnover"]])
                volume = float(f[_IDX["volume"]])
            except ValueError:
                continue
            date_str, time_str = f[_IDX["date"]], f[_IDX["time"]]
            try:
                ts = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                ts = datetime.now()
            change = now - prev_close
            change_pct = change / prev_close * 100 if prev_close else 0.0
            # 五档盘口：f[10..29]，每档「挂单量(股), 价格」交替，买 10 个值 + 卖 10 个值
            bids = [
                DepthLevel(price=float(f[11 + 2 * i]), volume=int(float(f[10 + 2 * i]) / 100))
                for i in range(5)
            ]
            asks = [
                DepthLevel(price=float(f[21 + 2 * i]), volume=int(float(f[20 + 2 * i]) / 100))
                for i in range(5)
            ]
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
                    bids=bids,
                    asks=asks,
                )
            )
        return quotes
