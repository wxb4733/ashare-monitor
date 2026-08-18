"""通知渠道：控制台输出（可扩展 webhook / 邮件等）。"""

from __future__ import annotations

import logging

from rich.console import Console

from .alerts import Alert

logger = logging.getLogger(__name__)
console = Console()


class Notifier:
    """通知器基类。"""

    def send(self, alert: Alert) -> None:
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    """控制台彩色输出。A 股习惯：涨红跌绿。"""

    def send(self, alert: Alert) -> None:
        style = "bold red" if "+" in alert.message or "上破" in alert.message else "bold green"
        console.print(f"[{style}]{alert}[/{style}]")
        logger.info("ALERT %s", alert)


class WebhookNotifier(Notifier):
    """Webhook 通知（如企业微信、钉钉机器人）。"""

    def __init__(self, url: str):
        self.url = url

    def send(self, alert: Alert) -> None:
        self.send_text(str(alert))

    def send_text(self, content: str) -> None:
        """推送纯文本消息（用于复盘摘要等非预警场景）。"""
        import requests

        try:
            resp = requests.post(
                self.url,
                json={"msgtype": "text", "text": {"content": content}},
                timeout=5,
            )
            resp.raise_for_status()
        except Exception:
            logger.exception("Webhook 通知发送失败: %s", content[:50])
