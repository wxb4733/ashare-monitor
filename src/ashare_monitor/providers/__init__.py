"""多行情源 Provider。

- sina / tencent / tencent_hk：解析逻辑借鉴自 easyquotation（MIT License，
  Copyright (c) 2018 shidenggui，https://github.com/shidenggui/easyquotation）
- eastmoney：基于 akshare 的东方财富快照
- binance：币安公开 REST API（无需 Key）

市场路由：watchlist 中每项用 market 字段标注（ashare/hk/crypto），
fetch_spot_quotes 按市场选择数据源链。
"""

from .base import QuoteProvider
from .binance import BinanceProvider
from .eastmoney import EastMoneyProvider
from .hk import TencentHKProvider
from .sina import SinaProvider
from .tencent import TencentProvider
from .us import SinaUSProvider, TencentUSProvider

PROVIDERS: dict[str, type[QuoteProvider]] = {
    "sina": SinaProvider,
    "tencent": TencentProvider,
    "tencent_hk": TencentHKProvider,
    "eastmoney": EastMoneyProvider,
    "binance": BinanceProvider,
    "tencent_us": TencentUSProvider,
    "sina_us": SinaUSProvider,
}

# 各市场默认数据源链（按顺序降级）
MARKET_SOURCES: dict[str, list[str]] = {
    "ashare": ["sina", "tencent", "eastmoney"],
    "hk": ["tencent_hk"],
    "us": ["sina_us", "tencent_us"],
    "crypto": ["binance"],
}

__all__ = [
    "QuoteProvider",
    "SinaProvider",
    "TencentProvider",
    "TencentHKProvider",
    "EastMoneyProvider",
    "BinanceProvider",
    "PROVIDERS",
    "MARKET_SOURCES",
]
