"""多行情源 Provider。

- sina / tencent：解析逻辑借鉴自 easyquotation（MIT License，
  Copyright (c) 2018 shidenggui，https://github.com/shidenggui/easyquotation）
- eastmoney：基于 akshare 的东方财富快照
"""

from .base import QuoteProvider
from .eastmoney import EastMoneyProvider
from .sina import SinaProvider
from .tencent import TencentProvider

PROVIDERS: dict[str, type[QuoteProvider]] = {
    "sina": SinaProvider,
    "tencent": TencentProvider,
    "eastmoney": EastMoneyProvider,
}

__all__ = [
    "QuoteProvider",
    "SinaProvider",
    "TencentProvider",
    "EastMoneyProvider",
    "PROVIDERS",
]
