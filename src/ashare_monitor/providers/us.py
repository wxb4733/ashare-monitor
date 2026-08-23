"""美股行情 Provider：腾讯（usNVDA）+ 新浪（gb_nvda）双源。

代码格式：NVDA / AAPL（纯字母）；内部转换为腾讯 usNVDA、新浪 gb_nvda。
解析逻辑借鉴 easyquotation 风格（腾讯/新浪美股字段布局）。

注意：美股为美元计价；字段与前收/开高低一致。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .base import Quote, QuoteProvider

logger = logging.getLogger(__name__)


class TencentUSProvider(QuoteProvider):
    """腾讯美股行情（qt.gtimg.cn/q=usNVDA）。"""

    name = "tencent_us"

    def fetch(self, codes: list[str]) -> list[Quote]:
        import requests

        params = ",".join(f"us{c.upper()}" for c in codes)
        resp = requests.get("https://qt.gtimg.cn/q=" + params,
                            headers={"User-Agent": "Mozilla/5.0"},
                            timeout=10)
        resp.encoding = "gbk"
        quotes = []
        for line in resp.text.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            body = line.split("=", 1)[1].strip('"')
            parts = body.split("~")
            if len(parts) < 10 or not parts[1]:
                continue
            quotes.append(self.parse(parts))
        return quotes

    @staticmethod
    def parse(p: list[str]) -> Quote:
        """解析腾讯美股字段（索引：3=现价 4=昨收 5=开盘 6=成交量…）。"""
        f = _f
        return Quote(
            code=p[2].split(".")[0] if "." in p[2] else p[2],
            name=p[1],
            price=f(p[3]),
            prev_close=f(p[4]),
            open=f(p[5]),
            volume=f(p[6]),
            turnover=None,
            change=None,
            change_pct=(f(p[3]) / f(p[4]) - 1) * 100
            if f(p[3]) and f(p[4]) else None,
            high=None,
            low=None,
            timestamp=datetime.now(tz=timezone.utc),
        )


class SinaUSProvider(QuoteProvider):
    """新浪美股行情（hq.sinajs.cn/list=gb_nvda）。"""

    name = "sina_us"

    def fetch(self, codes: list[str]) -> list[Quote]:
        import requests

        params = ",".join(f"gb_{c.lower()}" for c in codes)
        resp = requests.get("https://hq.sinajs.cn/list=" + params,
                            headers={
                                "User-Agent": "Mozilla/5.0",
                                "Referer": "https://finance.sina.com.cn",
                            },
                            timeout=10)
        resp.encoding = "gbk"
        quotes = []
        for line in resp.text.strip().split("\n"):
            if "=" not in line or '"' not in line:
                continue
            name = line.split('"')[0].split("=")[0].split("_")[-1].upper()
            body = line.split('"')[1]
            parts = body.split(",")
            if len(parts) < 8:
                continue
            quotes.append(self.parse(name, parts))
        return quotes

    @staticmethod
    def parse(code: str, p: list[str]) -> Quote:
        """解析新浪美股（索引：0=名称 1=现价 2=涨跌幅% 4=涨跌额 5=开盘 6=最高 7=最低…）。"""
        f = _f
        return Quote(
            code=code,
            name=p[0] or code,
            price=f(p[1]),
            prev_close=f(p[1]) - f(p[4]) if f(p[1]) and f(p[4]) else None,
            open=f(p[5]),
            volume=None,
            turnover=None,
            change=f(p[4]),
            change_pct=f(p[2]),
            high=f(p[6]),
            low=f(p[7]),
            timestamp=datetime.now(tz=timezone.utc),
        )


def _f(v) -> float | None:
    try:
        if v in (None, "", "--", "0"):
            return None if v in (None, "", "--") else 0.0
        return float(v)
    except (TypeError, ValueError):
        return None
