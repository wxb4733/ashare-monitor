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

        return [a for a in alerts if a is not None]

    def _make_alert(self, quote: Quote, rule: str, message: str) -> Alert | None:
        key = (quote.code, rule)
        if key in self._triggered:
            return None  # 冷却中，不重复告警
        self._triggered.add(key)
        return Alert(code=quote.code, name=quote.name, rule=rule, message=message)
