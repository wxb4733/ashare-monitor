"""行情 Provider 基类。"""

from __future__ import annotations

import abc

from ..quotes import Quote


def get_market_prefix(stock_code: str) -> str:
    """判断证券代码对应的市场前缀（sh/sz/bj）。

    规则借鉴自 easyquotation.helpers.get_stock_type（MIT License）：
    - 43/83/87/92 开头为北交所 bj
    - 5/6/7/9 及部分债券代码开头为上交所 sh
    - 其余为深交所 sz
    """
    assert isinstance(stock_code, str), "stock code need str type"
    if stock_code.startswith(("sh", "sz", "zz", "bj")):
        return stock_code[:2]
    code = stock_code[-6:]
    if code.startswith(("43", "83", "87", "92")):
        return "bj"
    if code.startswith(("5", "6", "7", "9", "110", "113", "118", "132", "204")):
        return "sh"
    return "sz"


class QuoteProvider(abc.ABC):
    """行情数据源抽象接口。"""

    #: 来源名称，用于日志与配置
    name: str = "base"
    #: 单次请求最大股票数（受行情网关 URL 长度限制）
    max_num: int = 60

    @abc.abstractmethod
    def fetch(self, codes: list[str]) -> list[Quote]:
        """拉取指定代码的实时行情，失败时抛出异常。"""
        raise NotImplementedError

    @staticmethod
    def _with_prefix(codes: list[str]) -> list[str]:
        return [get_market_prefix(c) + c[-6:] for c in codes]
