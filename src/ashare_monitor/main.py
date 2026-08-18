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
from .analysis import HistoryReport, ProfileCache
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
    has_depth = any(q.bids or q.asks for q in quotes)
    table = Table(title=f"A 股实时行情  {datetime.now():%Y-%m-%d %H:%M:%S}")
    columns = ["代码", "名称", "最新价", "涨跌幅", "涨跌额", "振幅", "成交量(手)", "成交额(万)"]
    if has_depth:
        columns += ["买一", "卖一", "委比"]
    for col in columns:
        table.add_column(col, justify="right" if col not in ("代码", "名称") else "left")

    for q in quotes:
        color = "red" if q.change_pct > 0 else ("green" if q.change_pct < 0 else "white")
        amp = q.amplitude
        row = [
            q.code,
            q.name,
            f"{q.price:.2f}",
            f"[{color}]{q.change_pct:+.2f}%[/{color}]",
            f"[{color}]{q.change:+.2f}[/{color}]",
            f"{amp:.2f}%" if amp is not None else "-",
            f"{q.volume:,.0f}",
            f"{q.turnover / 1e4:,.0f}",
        ]
        if has_depth:
            bid1 = f"{q.bids[0].price:.2f}/{q.bids[0].volume}" if q.bids else "-"
            ask1 = f"{q.asks[0].price:.2f}/{q.asks[0].volume}" if q.asks else "-"
            weibi = q.weibi
            row += [
                f"[green]{bid1}[/green]" if q.bids else "-",
                f"[red]{ask1}[/red]" if q.asks else "-",
                f"{weibi:+.0f}%" if weibi is not None else "-",
            ]
        table.add_row(*row)
    console.print(table)


def snapshot(
    codes: list[str],
    notifiers: list[Notifier],
    engine: AlertEngine,
    sources: list[str] | None = None,
    profile_cache: "ProfileCache | None" = None,
) -> None:
    quotes, source = fetch_spot_quotes(codes, sources=sources)
    if not quotes:
        console.print("[yellow]未获取到行情数据（可能不在交易时段或网络异常）[/yellow]")
        return
    render_quotes(quotes)
    console.print(f"[dim]数据源: {source}[/dim]")
    for q in quotes:
        for alert in engine.check(q):
            if profile_cache is not None:
                # 预警触发时附带该股近期波动画像（按交易日缓存，失败不阻塞）
                alert.profile = profile_cache.get(q.code)
            for n in notifiers:
                n.send(alert)


def render_baseline(codes: list[str], cache: "ProfileCache") -> None:
    """监控启动时输出自选股历史波动基线。"""
    table = Table(title="自选股波动基线（历史数据分析）")
    table.add_column("代码", justify="left")
    table.add_column("近期波动画像", justify="left")
    for code in codes:
        profile = cache.get(code)
        table.add_row(code, profile or "[dim]画像拉取失败[/dim]")
    console.print(table)


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

    profile_cache: ProfileCache | None = None
    if cfg.monitor.startup_profile or cfg.monitor.alert_profile:
        profile_cache = ProfileCache(days=cfg.monitor.profile_days)
        if cfg.monitor.startup_profile:
            render_baseline(codes, profile_cache)

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
                snapshot(
                    codes, notifiers, engine,
                    sources=cfg.quotes.sources,
                    profile_cache=profile_cache if cfg.monitor.alert_profile else None,
                )
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


def _pct_text(value: float, digits: int = 2) -> str:
    """百分比文本，涨红跌绿。"""
    color = "red" if value > 0 else ("green" if value < 0 else "white")
    return f"[{color}]{value:+.{digits}f}%[/{color}]"


def render_report(r: HistoryReport) -> None:
    """渲染历史数据分析报告。"""
    from rich.panel import Panel

    title = f"{r.name}({r.code})" if r.name else r.code
    console.print(Panel.fit(
        f"[bold]{title} 历史数据分析[/bold]\n"
        f"[dim]{r.start_date} ~ {r.end_date}，共 {r.bars} 个交易日[/dim]",
        border_style="cyan",
    ))

    overview = Table(show_header=False, box=None, padding=(0, 2))
    overview.add_column(style="dim")
    overview.add_column()
    overview.add_row("最新收盘", f"[bold]{r.latest_close:.2f}[/bold]")
    overview.add_row("区间涨跌幅", _pct_text(r.period_return_pct))
    overview.add_row("上涨/下跌天数", f"[red]{r.up_days}[/red] / [green]{r.down_days}[/green]"
                     f"（胜率 {r.win_rate:.0f}%）")
    console.print(overview)

    vol_table = Table(title="波动指标")
    for col in ("年化波动率", "近20日波动率", "最大回撤", "平均日振幅"):
        vol_table.add_column(col, justify="right")
    vol_table.add_row(
        f"{r.annual_volatility_pct:.2f}%",
        f"{r.recent20_volatility_pct:.2f}%",
        _pct_text(r.max_drawdown_pct),
        f"{r.avg_amplitude_pct:.2f}%",
    )
    console.print(vol_table)

    if r.ma:
        ma_table = Table(title="趋势（均线）")
        ma_table.add_column("指标", justify="right")
        for n in r.ma:
            ma_table.add_column(f"MA{n}", justify="right")
        values = [f"{v:.2f}" for v in r.ma.values()]
        ma_table.add_row("数值", *values)
        positions = []
        for v in r.ma.values():
            above = r.latest_close >= v
            positions.append("[red]上方[/red]" if above else "[green]下方[/green]")
        ma_table.add_row("收盘位置", *positions)
        console.print(ma_table)

    vol_ratio = r.volume_ratio
    vol_text = f"{vol_ratio:.2f}" if vol_ratio is not None else "-"
    console.print(
        f"[dim]量能：近5日均量 {r.volume_ma5:,.0f} 手 / 近20日均量 "
        f"{r.volume_ma20:,.0f} 手，量比 {vol_text}[/dim]"
    )


def run_analyze(code: str, days: int, adjust: str) -> None:
    from .analysis import analyze

    console.print(f"[cyan]正在拉取 {code} 历史数据（近 {days} 个交易日）…[/cyan]")
    try:
        report = analyze(code, days=days, adjust=adjust)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]分析失败：{exc}[/red]")
        return
    render_report(report)


def main() -> None:
    parser = argparse.ArgumentParser(description="A 股交易信息监控")
    parser.add_argument("--config", help="配置文件路径（默认 config.yaml）")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("monitor", help="持续监控（默认命令）")
    sub.add_parser("once", help="获取一次行情快照后退出")
    p_analyze = sub.add_parser("analyze", help="拉取个股历史数据并分析")
    p_analyze.add_argument("code", help="6 位证券代码，如 600519")
    p_analyze.add_argument("--days", type=int, default=250, help="回看交易日数（默认 250）")
    p_analyze.add_argument("--adjust", default="qfq",
                           choices=["qfq", "hfq", ""], help="复权方式（默认 qfq 前复权）")

    args = parser.parse_args()
    if args.command == "once":
        run_once(args.config)
    elif args.command == "analyze":
        run_analyze(args.code, args.days, args.adjust)
    else:
        run_monitor(args.config)


if __name__ == "__main__":
    main()
