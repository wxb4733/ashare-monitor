"""实盘执行通道适配器（Phase B 占位）。

合规说明：低频自动化实盘需券商程序化交易通道（QMT/PTrade）+ 合规开通。
本目录为接口占位——券商开通后填入真实 API 调用（见 qmt.py / ptrade.py）。

架构：策略/风控 → Executor.execute(orders) → 券商通道。
当前仅 paper（模拟）实现，见 strategy.execute_paper_trade / execute_rebalance。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def execute(orders: list[dict], channel: str = "paper") -> dict:
    """按通道执行指令（paper=模拟；qmt/ptrade=券商实盘，占位未实现）。"""
    if channel == "paper":
        from ..strategy import execute_paper_trade, execute_rebalance

        buys = [o for o in orders if o["side"] == "buy"]
        sells = [o for o in orders if o["side"] == "sell"]
        return execute_rebalance(orders) if sells else execute_paper_trade(buys)
    raise NotImplementedError(
        f"实盘通道 {channel} 未实现：需券商开通 QMT/PTrade 后接入（合规）")
