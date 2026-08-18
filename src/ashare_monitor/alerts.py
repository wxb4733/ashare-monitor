"""预警引擎：根据规则检测行情异动。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import AlertConfig
from .quotes import Quote

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    code: str
    name: str
    rule: str      # 触发的规则描述
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.name}({self.code}): {self.message}"


class AlertEngine:
    """对行情快照应用预警规则。

    内置去抖：同一代码同一规则在触发后进入冷却，价格回归阈值内后重置，
    避免行情在阈值附近波动时反复告警。
    """

    def __init__(self, config: AlertConfig):
        self.config = config
        self._triggered: set[tuple[str, str]] = set()

    def check(self, quote: Quote) -> list[Alert]:
        alerts: list[Alert] = []

        # 涨跌幅阈值
        threshold = self.config.change_pct_threshold
        if abs(quote.change_pct) >= threshold:
            alerts.append(self._make_alert(
                quote, "change_pct",
                f"涨跌幅 {quote.change_pct:+.2f}%，超过阈值 ±{threshold:.1f}%（最新价 {quote.price:.2f}）",
            ))
        else:
            self._triggered.discard((quote.code, "change_pct"))

        # 价格上破
        above = self.config.price_above.get(quote.code)
        if above is not None:
            if quote.price >= above:
                alerts.append(self._make_alert(
                    quote, "price_above",
                    f"价格 {quote.price:.2f} 上破 {above:.2f}",
                ))
            else:
                self._triggered.discard((quote.code, "price_above"))

        # 价格下破
        below = self.config.price_below.get(quote.code)
        if below is not None:
            if quote.price <= below:
                alerts.append(self._make_alert(
                    quote, "price_below",
                    f"价格 {quote.price:.2f} 下破 {below:.2f}",
                ))
            else:
                self._triggered.discard((quote.code, "price_below"))

        # 委比异动（需五档盘口数据）
        weibi_threshold = self.config.weibi_threshold
        if weibi_threshold is not None:
            weibi = quote.weibi
            if weibi is not None and abs(weibi) >= weibi_threshold:
                side = "买盘" if weibi > 0 else "卖盘"
                alerts.append(self._make_alert(
                    quote, "weibi",
                    f"委比 {weibi:+.1f}%，{side}力量显著占优（阈值 ±{weibi_threshold:.0f}%）",
                ))
            else:
                self._triggered.discard((quote.code, "weibi"))

        # 单档大单挂单
        big_threshold = self.config.big_order_threshold
        if big_threshold is not None and (quote.bids or quote.asks):
            big = self._find_big_order(quote, big_threshold)
            if big is not None:
                side, level, depth = big
                alerts.append(self._make_alert(
                    quote, "big_order",
                    f"{side}{level}档出现大单挂单 {depth.volume:,} 手 @ {depth.price:.2f}"
                    f"（阈值 {big_threshold:,.0f} 手）",
                ))
            else:
                self._triggered.discard((quote.code, "big_order"))

        # 振幅波动
        amp_threshold = self.config.amplitude_threshold
        if amp_threshold is not None:
            amp = quote.amplitude
            if amp is not None and amp >= amp_threshold:
                alerts.append(self._make_alert(
                    quote, "amplitude",
                    f"当日振幅 {amp:.2f}%，波动超过阈值 {amp_threshold:.1f}%"
                    f"（{quote.low:.2f} ~ {quote.high:.2f}）",
                ))
            else:
                self._triggered.discard((quote.code, "amplitude"))

        return [a for a in alerts if a is not None]

    @staticmethod
    def _find_big_order(quote: Quote, threshold: float):
        """返回 (方向, 档位, DepthLevel)，无大单返回 None。"""
        for i, d in enumerate(quote.bids, 1):
            if d.volume >= threshold:
                return ("买", i, d)
        for i, d in enumerate(quote.asks, 1):
            if d.volume >= threshold:
                return ("卖", i, d)
        return None

    def _make_alert(self, quote: Quote, rule: str, message: str) -> Alert | None:
        key = (quote.code, rule)
        if key in self._triggered:
            return None  # 冷却中，不重复告警
        self._triggered.add(key)
        return Alert(code=quote.code, name=quote.name, rule=rule, message=message)
