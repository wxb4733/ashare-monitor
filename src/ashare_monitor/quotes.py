"""行情数据获取：统一 Quote 模型 + 多数据源自动降级。

数据源优先级可在 config.yaml 的 quotes.sources 中配置，
默认 sina → tencent → eastmoney（借鉴 easyquotation 的新浪/腾讯源
速度快、开销低，适合盘中轮询；东财字段全，作为兜底）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

# 默认数据源顺序：新浪/腾讯按需查询快，东财全市场快照兜底
DEFAULT_SOURCES = ["sina", "tencent", "eastmoney"]


@dataclass
class DepthLevel:
    """盘口单档：价格 + 挂单量（手）。"""
    price: float
    volume: int


@dataclass
class Quote:
    code: str
    name: str
    price: float          # 最新价
    change_pct: float     # 涨跌幅 %
    change: float         # 涨跌额
    volume: float         # 成交量（手）
    turnover: float       # 成交额（元）
    high: float
    low: float
    open: float
    prev_close: float     # 昨收
    timestamp: datetime
    bids: list[DepthLevel] = field(default_factory=list)  # 买一至买五
    asks: list[DepthLevel] = field(default_factory=list)  # 卖一至卖五

    @property
    def weibi(self) -> float | None:
        """委比 %：(Σ买档量 - Σ卖档量) / (Σ买档量 + Σ卖档量) × 100。"""
        bid_vol = sum(d.volume for d in self.bids)
        ask_vol = sum(d.volume for d in self.asks)
        total = bid_vol + ask_vol
        if total == 0:
            return None
        return (bid_vol - ask_vol) / total * 100


def fetch_spot_quotes(
    codes: list[str],
    sources: list[str] | None = None,
) -> tuple[list[Quote], str]:
    """获取指定代码的实时行情，按优先级尝试多个数据源。

    :param codes: 6 位证券代码列表
    :param sources: 数据源名称列表（sina/tencent/eastmoney），None 用默认顺序
    :return: (行情列表, 实际使用的数据源名)
    :raises RuntimeError: 所有数据源均失败
    """
    from .providers import PROVIDERS

    errors: dict[str, Exception] = {}
    for name in sources or DEFAULT_SOURCES:
        provider_cls = PROVIDERS.get(name)
        if provider_cls is None:
            logger.warning("未知数据源: %s，跳过", name)
            continue
        try:
            quotes = provider_cls().fetch(codes)
        except Exception as exc:  # noqa: BLE001 - 单源失败不应中断
            logger.warning("数据源 %s 拉取失败: %s", name, exc)
            errors[name] = exc
            continue
        if quotes:
            return quotes, name
        errors[name] = ValueError("返回空数据")

    raise RuntimeError(
        "所有行情数据源均不可用: "
        + "; ".join(f"{k}: {v}" for k, v in errors.items())
    )


def fetch_index_quotes() -> pd.DataFrame:
    """获取主要指数行情（上证、深证、创业板等）。"""
    import akshare as ak

    return ak.stock_zh_index_spot_em()


def is_trading_time(sessions: list[list[str]], now: datetime | None = None) -> bool:
    """判断当前是否处于交易时段（周一至周五且在交易时间段内）。"""
    now = now or datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    current = now.strftime("%H:%M")
    return any(start <= current <= end for start, end in sessions)
