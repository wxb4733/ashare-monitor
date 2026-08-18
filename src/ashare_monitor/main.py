"""命令行入口：实时监控 / 单次快照。"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime

from rich.console import Console
from rich.table import Table

from .alerts import AlertEngine
from .config import load_config
from .notify import ConsoleNotifier, Notifier
from .quotes import Quote, fetch_spot_quotes, is_trading_time

console = Console()
logger = logging.getLogger(__name__)


def setup_logging(cfg: dict) -> None:
    level = getattr(logging, str(cfg.get("level", "INFO")).upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = cfg.get("file")
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def render_quotes(quotes: list[Quote]) -> None:
    """以表格形式打印行情快照（A 股习惯：涨红跌绿）。"""
    table = Table(title=f"A 股实时行情  {datetime.now():%Y-%m-%d %H:%M:%S}")
    for col in ("代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量(手)", "成交额(万)"):
        table.add_column(col, justify="right" if col not in ("代码", "名称") else "left")

    for q in quotes:
        color = "red" if q.change_pct > 0 else ("green" if q.change_pct < 0 else "white")
        table.add_row(
            q.code,
            q.name,
            f"{q.price:.2f}",
            f"[{color}]{q.change_pct:+.2f}%[/{color}]",
            f"[{color}]{q.change:+.2f}[/{color}]",
            f"{q.volume:,.0f}",
            f"{q.turnover / 1e4:,.0f}",
        )
    console.print(table)


def snapshot(
    codes: list[str],
    notifiers: list[Notifier],
    engine: AlertEngine,
    sources: list[str] | None = None,
) -> None:
    quotes, source = fetch_spot_quotes(codes, sources=sources)
    if not quotes:
        console.print("[yellow]未获取到行情数据（可能不在交易时段或网络异常）[/yellow]")
        return
    render_quotes(quotes)
    console.print(f"[dim]数据源: {source}[/dim]")
    for q in quotes:
        for alert in engine.check(q):
            for n in notifiers:
                n.send(alert)


def run_monitor(config_path: str | None) -> None:
    cfg = load_config(config_path)
    setup_logging(cfg.logging)

    codes = [str(item["code"]) for item in cfg.watchlist]
    if not codes:
        console.print("[red]config.yaml 中 watchlist 为空，请先配置自选股[/red]")
        return

    engine = AlertEngine(cfg.alerts)
    notifiers: list[Notifier] = [ConsoleNotifier()]
    webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
    if webhook:
        from .notify import WebhookNotifier

        notifiers.append(WebhookNotifier(webhook))

    interval = cfg.monitor.interval_seconds
    console.print(
        f"[cyan]开始监控 {len(codes)} 只股票，间隔 {interval}s，Ctrl+C 退出[/cyan]"
    )

    try:
        while True:
            if cfg.monitor.trading_hours_only and not is_trading_time(
                cfg.monitor.trading_sessions
            ):
                logger.debug("非交易时段，等待 %ds", interval)
                time.sleep(interval)
                continue
            try:
                snapshot(codes, notifiers, engine, sources=cfg.quotes.sources)
            except Exception:
                logger.exception("本轮行情获取失败")
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[cyan]监控已停止[/cyan]")


def run_once(config_path: str | None) -> None:
    cfg = load_config(config_path)
    setup_logging(cfg.logging)
    codes = [str(item["code"]) for item in cfg.watchlist]
    if not codes:
        console.print("[red]config.yaml 中 watchlist 为空[/red]")
        return
    snapshot(codes, [ConsoleNotifier()], AlertEngine(cfg.alerts), sources=cfg.quotes.sources)


def main() -> None:
    parser = argparse.ArgumentParser(description="A 股交易信息监控")
    parser.add_argument("--config", help="配置文件路径（默认 config.yaml）")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("monitor", help="持续监控（默认命令）")
    sub.add_parser("once", help="获取一次行情快照后退出")

    args = parser.parse_args()
    if args.command == "once":
        run_once(args.config)
    else:
        run_monitor(args.config)


if __name__ == "__main__":
    main()
