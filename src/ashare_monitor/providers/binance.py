"""币安（Binance）加密货币行情源。

使用公开 REST API（无需 API Key）：
- 24h 行情：GET /api/v3/ticker/24hr?symbol=BTCUSDT
- K 线：GET /api/v3/klines?symbol=BTCUSDT&interval=1d&limit=N

主域名 api.binance.com 在部分网络环境不可达，
自动降级公共数据镜像 data-api.binance.vision。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from ..quotes import Quote
from .base import QuoteProvider

logger = logging.getLogger(__name__)

_HOSTS = [
    "https://api.binance.com",
    "https://data-api.binance.vision",
]

_HEADERS = {"User-Agent": "ashare-monitor/0.1"}


def _get(path: str, params: dict) -> requests.Response:
    """按序尝试主备域名，返回首个成功的响应。"""
    last_exc: Exception | None = None
    for host in _HOSTS:
        try:
            resp = requests.get(host + path, params=params,
                                headers=_HEADERS, timeout=10)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            logger.debug("币安 %s 请求失败: %s", host, exc)
            last_exc = exc
    raise ConnectionError(f"币安所有域名均不可达: {last_exc}")


def _normalize_symbol(code: str) -> str:
    """接受 BTCUSDT / btcusdt / BTC-USDT 等写法，统一为 BTCUSDT。"""
    return code.replace("-", "").replace("/", "").upper()


class BinanceProvider(QuoteProvider):
    """币安 24 小时行情。代码为交易对，如 BTCUSDT。7×24 不间断。"""

    name = "binance"

    def fetch(self, codes: list[str]) -> list[Quote]:
        quotes: list[Quote] = []
        for code in codes:
            symbol = _normalize_symbol(code)
            resp = _get("/api/v3/ticker/24hr", {"symbol": symbol})
            quotes.append(self.parse(resp.json()))
        return quotes

    @staticmethod
    def parse(data: dict) -> Quote:
        """解析单个 24hr ticker JSON 为 Quote（独立出来便于测试）。"""
        last = float(data["lastPrice"])
        change = float(data["priceChange"])
        ts = datetime.fromtimestamp(int(data["closeTime"]) / 1000, tz=timezone.utc)
        return Quote(
            code=data["symbol"],
            name=data["symbol"],
            price=last,
            prev_close=last - change,
            open=float(data["openPrice"]),
            volume=float(data["volume"]),            # 成交量（基础币，如 BTC）
            turnover=float(data["quoteVolume"]),     # 成交额（计价币，如 USDT）
            change=change,
            change_pct=float(data["priceChangePercent"]),
            high=float(data["highPrice"]),
            low=float(data["lowPrice"]),
            timestamp=ts,
        )


def fetch_klines(symbol: str, days: int, interval: str = "1d") -> list[list]:
    """拉取 K 线，返回原始 klines 列表。

    :param interval: 1d（日）/ 1w（周）/ 1M（月）
    """
    resp = _get("/api/v3/klines", {
        "symbol": _normalize_symbol(symbol),
        "interval": interval,
        "limit": min(days, 1000),
    })
    return resp.json()
