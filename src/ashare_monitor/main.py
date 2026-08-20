"""命令行入口：实时监控 / 单次快照。"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timedelta

from rich.console import Console
from rich.table import Table

from .alerts import AlertEngine
from .analysis import HistoryReport, ProfileCache
from .config import load_config
from .notify import ConsoleNotifier, Notifier
from .quotes import Quote, fetch_spot_quotes, is_market_open, is_trading_time

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


def group_by_market(watchlist: list[dict]) -> dict[str, list[str]]:
    """把 watchlist 按市场分组：{market: [code, ...]}，默认 ashare。"""
    groups: dict[str, list[str]] = {}
    for item in watchlist:
        market = str(item.get("market", "ashare"))
        groups.setdefault(market, []).append(str(item["code"]))
    return groups


def snapshot(
    codes: list[str],
    notifiers: list[Notifier],
    engine: AlertEngine,
    sources: list[str] | None = None,
    profile_cache: "ProfileCache | None" = None,
    market: str = "ashare",
) -> list:
    """获取一轮行情快照并应用预警规则，返回本轮触发的预警列表。"""
    fired = []
    quotes, source = fetch_spot_quotes(codes, sources=sources, market=market)
    if not quotes:
        console.print(f"[yellow]{market} 未获取到行情数据（可能不在交易时段或网络异常）[/yellow]")
        return fired
    render_quotes(quotes)
    console.print(f"[dim]市场: {market} | 数据源: {source}[/dim]")
    for q in quotes:
        for alert in engine.check(q):
            if profile_cache is not None:
                # 预警触发时附带该股近期波动画像（按交易日缓存，失败不阻塞）
                alert.profile = profile_cache.get(q.code, market)
            fired.append(alert)
            for n in notifiers:
                n.send(alert)
    return fired


def render_baseline(groups: dict[str, list[str]], cache: "ProfileCache") -> None:
    """监控启动时输出自选股历史波动基线。"""
    table = Table(title="自选股波动基线（历史数据分析）")
    table.add_column("市场", justify="left")
    table.add_column("代码", justify="left")
    table.add_column("近期波动画像", justify="left")
    for market, codes in groups.items():
        for code in codes:
            profile = cache.get(code, market)
            table.add_row(market, code, profile or "[dim]画像拉取失败[/dim]")
    console.print(table)


def run_monitor(config_path: str | None) -> None:
    from .review import append_alerts, generate_review

    cfg = load_config(config_path)
    setup_logging(cfg.logging)

    groups = group_by_market(cfg.watchlist)
    if not groups:
        console.print("[red]config.yaml 中 watchlist 为空，请先配置自选股[/red]")
        return
    total = sum(len(v) for v in groups.values())

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
            render_baseline(groups, profile_cache)

    interval = cfg.monitor.interval_seconds
    market_desc = ", ".join(f"{m}×{len(c)}" for m, c in groups.items())
    console.print(
        f"[cyan]开始监控 {total} 只标的（{market_desc}），间隔 {interval}s，Ctrl+C 退出[/cyan]"
    )

    was_trading = False      # A 股是否经历过交易时段（用于收盘复盘判定）
    reviewed_date = ""       # 已生成复盘报告的日期，避免重复

    try:
        while True:
            now = datetime.now()
            in_ashare_session = is_trading_time(cfg.monitor.trading_sessions, now)

            # A 股收盘转折点：自动生成当日复盘报告
            today = now.strftime("%Y-%m-%d")
            if (
                was_trading
                and not in_ashare_session
                and cfg.monitor.auto_review
                and reviewed_date != today
                and _is_after_close(cfg.monitor.trading_sessions, now)
            ):
                reviewed_date = today
                console.print("[cyan]已收盘，正在生成复盘报告…[/cyan]")
                try:
                    from .review import build_push_summary

                    path, day_quotes, day_records = generate_review(today, cfg)
                    console.print(f"[green]复盘报告已生成: {path}[/green]")
                    try:
                        from .storage import save_review

                        save_review(today, str(path), day_quotes, day_records)
                    except Exception:
                        logger.exception("复盘记录 SQLite 落盘失败")
                    for n in notifiers:
                        if hasattr(n, "send_text"):
                            n.send_text(build_push_summary(
                                today, day_quotes, day_records, path
                            ))
                except Exception:
                    logger.exception("复盘报告生成失败")

            any_active = False
            for market, mcodes in groups.items():
                if cfg.monitor.trading_hours_only and not is_market_open(
                    market, cfg.monitor.trading_sessions, now
                ):
                    continue
                any_active = True
                if market == "ashare":
                    was_trading = True
                try:
                    fired = snapshot(
                        mcodes, notifiers, engine,
                        sources=cfg.quotes.sources if market == "ashare" else None,
                        profile_cache=profile_cache if cfg.monitor.alert_profile else None,
                        market=market,
                    )
                    if fired:
                        append_alerts(fired)
                        try:
                            from .storage import record_alerts

                            record_alerts(fired, market=market)
                        except Exception:
                            logger.exception("预警 SQLite 落盘失败（%s）", market)
                except Exception:
                    logger.exception("本轮行情获取失败（%s）", market)
            if not any_active:
                logger.debug("所有市场均闭市，等待 %ds", interval)
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[cyan]监控已停止[/cyan]")


def _is_after_close(sessions: list[list[str]], now: datetime) -> bool:
    """当前时间是否已过当天最后一个交易时段的结束时间（且为工作日）。"""
    if now.weekday() >= 5:
        return False
    current = now.strftime("%H:%M")
    last_end = max(end for _, end in sessions)
    return current > last_end


def run_once(config_path: str | None) -> None:
    cfg = load_config(config_path)
    setup_logging(cfg.logging)
    groups = group_by_market(cfg.watchlist)
    if not groups:
        console.print("[red]config.yaml 中 watchlist 为空[/red]")
        return
    for market, codes in groups.items():
        try:
            snapshot(
                codes, [ConsoleNotifier()], AlertEngine(cfg.alerts),
                sources=cfg.quotes.sources if market == "ashare" else None,
                market=market,
            )
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]{market} 行情获取失败：{exc}[/red]")


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


def render_signals(signals: list, verdict) -> None:
    """渲染规则信号表与综合研判。"""
    if not signals:
        return
    table = Table(title="交易信号（规则化，仅供参考）")
    table.add_column("信号", justify="left")
    table.add_column("方向", justify="center")
    table.add_column("说明", justify="left")
    for s in signals:
        if s.direction == "bullish":
            style, label = "red", "偏多"
        elif s.direction == "bearish":
            style, label = "green", "偏空"
        else:
            style, label = "yellow", "中性"
        table.add_row(s.name, f"[{style}]{label}[/{style}]", s.detail)
    console.print(table)
    v_style = "red" if verdict.direction == "偏多" else (
        "green" if verdict.direction == "偏空" else "yellow"
    )
    console.print(
        f"综合研判：[{v_style}]{verdict.direction}[/{v_style}] "
        f"（多空净得分 {verdict.score:+d}，信号一致度 {verdict.confidence:.0%}）"
    )


def print_disclaimer() -> None:
    from .signals import DISCLAIMER

    console.print(f"[dim]{DISCLAIMER}[/dim]")


def _trend_label(trend: str) -> str:
    style = "red" if trend == "金叉" else ("green" if trend == "死叉" else "yellow")
    return f"[{style}]{trend}[/{style}]"


def render_indicators(ir) -> None:
    """渲染技术指标板块（MACD / RSI / KDJ / BOLL）。"""
    m = ir.macd
    cross_info = ""
    if m.last_cross_date:
        cross_info = f"，最近{m.trend} {m.last_cross_date}（{m.days_since_cross}日前）"
    table = Table(title="技术指标")
    table.add_column("指标", justify="left")
    table.add_column("状态", justify="center")
    table.add_column("数值", justify="right")
    table.add_row("MACD", _trend_label(m.trend), f"DIF {m.dif:.3f} / DEA {m.dea:.3f} / 柱 {m.hist:.3f}{cross_info}")
    table.add_row("RSI(14)", ir.rsi.level, f"{ir.rsi.value:.1f}（6日 {ir.rsi.rsi6:.0f} / 24日 {ir.rsi.rsi24:.0f}）")
    table.add_row("KDJ(9)", f"{_trend_label(ir.kdj.trend)} / {ir.kdj.level}",
                  f"K {ir.kdj.k:.1f} / D {ir.kdj.d:.1f} / J {ir.kdj.j:.1f}")
    table.add_row("BOLL(20,2)", ir.boll.position,
                  f"上轨 {ir.boll.upper:.2f} / 中轨 {ir.boll.mid:.2f} / 下轨 {ir.boll.lower:.2f}"
                  f"（带宽 {ir.boll.bandwidth:.1f}%）")
    console.print(table)


def run_indicator(code: str, market: str, days: int, config_path: str | None,
                  period: str = "daily") -> None:
    """查看指定标的的技术指标（MACD/RSI/KDJ/BOLL，支持日/周/月线）。"""
    from .analysis import fetch_history
    from .indicators import compute_indicators
    from .quotes import fetch_spot_quotes

    cfg = load_config(config_path)
    period_label = {"daily": "日线", "weekly": "周线", "monthly": "月线"}.get(period, period)
    console.print(f"[cyan]正在获取 {code}（{market}）{period_label}历史数据与技术指标…[/cyan]")
    try:
        quotes, _source = fetch_spot_quotes(
            [code], sources=cfg.quotes.sources if market == "ashare" else None,
            market=market,
        )
        price = quotes[0].price if quotes else None
        adjust = "qfq" if market != "crypto" else ""
        df, name = fetch_history(code, days=days, adjust=adjust, market=market,
                                 period=period)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]指标获取失败：{exc}[/red]")
        return
    ir = compute_indicators(df, price=price)
    console.print(f"[bold cyan]{name or code}({code}) 技术指标（{period_label}）  "
                  f"{datetime.now():%Y-%m-%d %H:%M:%S}[/bold cyan]")
    if price:
        console.print(f"现价 [bold]{price:.2f}[/bold] | 数据源 {_source}")
    render_indicators(ir)
    console.print(f"[dim]指标摘要：{ir.summary_line()}[/dim]")
    print_disclaimer()


def run_analyze(code: str, days: int, adjust: str, market: str,
                period: str = "daily") -> None:
    from .analysis import analyze
    from .signals import generate_signals, make_verdict

    period_label = {"daily": "日线", "weekly": "周线", "monthly": "月线"}.get(period, period)
    console.print(
        f"[cyan]正在拉取 {code}（{market}）{period_label}历史数据（近 {days} 根）…[/cyan]"
    )
    try:
        report = analyze(code, days=days, adjust=adjust, market=market, period=period)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]分析失败：{exc}[/red]")
        return
    render_report(report)
    signals = generate_signals(report)
    render_signals(signals, make_verdict(signals))
    print_disclaimer()


def run_advice(code: str, market: str, days: int, config_path: str | None) -> None:
    """结合实时行情 + 历史分析，输出规则化交易信号。"""
    from .quotes import fetch_spot_quotes
    from .signals import SignalConfig, generate_signals, make_verdict

    cfg = load_config(config_path)
    console.print(
        f"[cyan]正在获取 {code}（{market}）实时行情与历史数据…[/cyan]"
    )
    try:
        quotes, _source = fetch_spot_quotes(
            [code], sources=cfg.quotes.sources if market == "ashare" else None,
            market=market,
        )
        quote = quotes[0] if quotes else None
        df, name = _fetch_history_for(code, market, days)
        from .analysis import TRADING_DAYS_PER_YEAR, compute_metrics

        periods = 365 if market == "crypto" else TRADING_DAYS_PER_YEAR
        report = compute_metrics(df, code=code, name=name, periods_per_year=periods)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]信号生成失败：{exc}[/red]")
        return

    title = f"{report.name or code}({code}) 交易信号  {datetime.now():%Y-%m-%d %H:%M:%S}"
    console.print(f"[bold cyan]{title}[/bold cyan]")
    if quote:
        console.print(
            f"实时价 [bold]{quote.price:.2f}[/bold]（{quote.change_pct:+.2f}%） "
            f"| 历史收盘 {report.latest_close:.2f} | 数据源 {_source}"
        )
    from .indicators import compute_indicators

    render_indicators(compute_indicators(df, price=quote.price if quote else None))
    signals = generate_signals(report, quote, cfg=SignalConfig(
        volume_ratio_high=cfg.signals.volume_ratio_high,
        volume_ratio_low=cfg.signals.volume_ratio_low,
        momentum_window=cfg.signals.momentum_window,
        momentum_pct=cfg.signals.momentum_pct,
    ))
    render_signals(signals, make_verdict(signals))
    print_disclaimer()


def _fetch_history_for(code: str, market: str, days: int):
    """advice 场景共用：拉取日线（一次网络请求，供指标计算）。"""
    from .analysis import fetch_history

    return fetch_history(
        code, days=days, adjust="qfq" if market != "crypto" else "", market=market
    )


def _render_news_tables(code: str, anns: list[dict], reports: list[dict]) -> None:
    """渲染公告/研报表。"""
    console.print(f"[bold cyan]{code} 最新公告（{len(anns)} 条）[/bold cyan]")
    ann_table = Table()
    ann_table.add_column("日期", justify="left")
    ann_table.add_column("标题", justify="left", overflow="fold")
    ann_table.add_column("链接", justify="left", overflow="fold")
    for a in anns:
        ann_table.add_row(a["date"], a["title"], a["url"])
    console.print(ann_table or "暂无公告")

    console.print(f"[bold cyan]{code} 近期研报（{len(reports)} 条）[/bold cyan]")
    rep_table = Table()
    rep_table.add_column("日期", justify="left")
    rep_table.add_column("机构", justify="left")
    rep_table.add_column("标题", justify="left", overflow="fold")
    rep_table.add_column("预测EPS", justify="right")
    rep_table.add_column("预测PE", justify="right")
    for r in reports:
        rep_table.add_row(
            r["date"], r["org"], r["title"],
            f"{r['eps_this_year']:.2f}" if r["eps_this_year"] is not None else "-",
            f"{r['pe_this_year']:.1f}" if r["pe_this_year"] is not None else "-",
        )
    console.print(rep_table or "暂无研报")


def run_news(code: str, market: str, days: int, config_path: str | None,
             local_only: bool = False, watchlist: bool = False) -> None:
    """查看标的的公告与研报（仅 A 股支持）。

    - 默认：网络拉取并入库（url 去重）
    - --local：仅读取数据库，不联网
    - --watchlist：批量采集全部 A 股自选股
    """
    from .announcements import fetch_announcements, fetch_research_reports
    from .storage import (
        load_announcements,
        load_research_reports,
        record_announcements,
        record_research_reports,
    )

    cfg = load_config(config_path)

    if watchlist:
        total_new = 0
        for item in cfg.watchlist:
            if str(item.get("market", "ashare")) != "ashare":
                continue
            c = str(item["code"])
            n = str(item.get("name", c))
            try:
                anns = fetch_announcements(c, limit=15)
                reps = fetch_research_reports(c, days=days, limit=15)
                na, ea = record_announcements(anns, c, name=n)
                nr, er = record_research_reports(reps, c, name=n)
                total_new += na + nr
                console.print(
                    f"[dim]{n}({c})：公告新增 {na}（已存 {ea}）| "
                    f"研报新增 {nr}（已存 {er}）[/dim]"
                )
            except Exception as exc:  # noqa: BLE001
                console.print(f"[yellow]{n}({c}) 采集失败：{exc}[/yellow]")
        console.print(f"[green]批量采集完成，共新增 {total_new} 条[/green]")
        return

    if market != "ashare":
        console.print("[yellow]公告/研报数据源仅支持 A 股，港股与加密货币暂无[/yellow]")
        return

    if local_only:
        anns = load_announcements(code, limit=30)
        reports = load_research_reports(code, limit=30)
        console.print(f"[cyan]{code} 数据库记录：公告 {len(anns)} 条 / 研报 {len(reports)} 条[/cyan]")
        _render_news_tables(code, anns, reports)
        return

    console.print(f"[cyan]正在获取 {code} 公告与研报并入库…[/cyan]")
    try:
        anns = fetch_announcements(code, limit=15)
        reports = fetch_research_reports(code, days=days, limit=15)
        na, ea = record_announcements(anns, code)
        nr, er = record_research_reports(reports, code)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]公告/研报获取失败：{exc}[/red]")
        return
    console.print(f"[dim]入库：公告新增 {na}（已存 {ea}）| 研报新增 {nr}（已存 {er}）[/dim]")
    _render_news_tables(code, anns, reports)


def run_financial(code: str, periods: int, market: str = "ashare") -> None:
    """查看标的的财报分析（A 股人民币 / 港股港元口径）。"""
    from .fundamentals import fetch_financials, summarize

    currency = "港元" if market == "hk" else "人民币"
    console.print(f"[cyan]正在获取 {code}（{market}）财报数据（近 {periods} 个报告期，"
                  f"{currency}口径）…[/cyan]")
    try:
        items = fetch_financials(code, periods=periods, market=market)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]财报获取失败：{exc}[/red]")
        return

    console.print(f"[bold cyan]{code} 财务业绩（最近 {len(items)} 期，{currency}）[/bold cyan]")
    table = Table()
    table.add_column("报告期", justify="left")
    table.add_column("营收(亿)", justify="right")
    table.add_column("营收同比", justify="right")
    table.add_column("净利(亿)", justify="right")
    table.add_column("净利同比", justify="right")
    table.add_column("ROE", justify="right")
    table.add_column("毛利率", justify="right")
    for p in items:
        def _fmt(v: float | None, suffix: str = "", nd: int = 2) -> str:
            return f"{v:.{nd}f}{suffix}" if v is not None else "-"

        rev_style = "red" if (p.revenue_yoy or 0) > 0 else (
            "green" if (p.revenue_yoy or 0) < 0 else ""
        )
        prof_style = "red" if (p.profit_yoy or 0) > 0 else (
            "green" if (p.profit_yoy or 0) < 0 else ""
        )
        rev_cell = (
            f"[{rev_style}]{_fmt(p.revenue_yoy, '%')}[/{rev_style}]"
            if rev_style else _fmt(p.revenue_yoy, "%")
        )
        prof_cell = (
            f"[{prof_style}]{_fmt(p.profit_yoy, '%')}[/{prof_style}]"
            if prof_style else _fmt(p.profit_yoy, "%")
        )
        table.add_row(
            p.report_date,
            _fmt(p.revenue), rev_cell,
            _fmt(p.net_profit), prof_cell,
            _fmt(p.roe, "%", 1), _fmt(p.gross_margin, "%", 1),
        )
    console.print(table)

    console.print("[bold cyan]财报速览[/bold cyan]")
    for line in summarize(items):
        console.print(f"  • {line}")
    print_disclaimer()


def run_review(date: str | None, config_path: str | None,
               backfill_start: str | None = None,
               backfill_end: str | None = None) -> None:
    if backfill_start:
        from .review import backfill_reviews

        cfg = load_config(config_path)
        setup_logging(cfg.logging)
        end = backfill_end or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        console.print(f"[cyan]正在回填 {backfill_start} ~ {end} 历史复盘报告"
                      f"（数据来源：本地 klines 库）…[/cyan]")
        try:
            files = backfill_reviews(backfill_start, end, cfg)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]历史复盘回填失败：{exc}[/red]")
            return
        console.print(f"[green]回填完成：共 {len(files)} 份复盘报告[/green]")
        for f in files[-6:]:
            console.print(f"  [dim]{f}[/dim]")
        if len(files) > 6:
            console.print(f"  [dim]…共 {len(files)} 份，以上为最后 6 份[/dim]")
        return

    from .review import generate_review

    cfg = load_config(config_path)
    setup_logging(cfg.logging)
    console.print("[cyan]正在生成复盘报告…[/cyan]")
    try:
        path, quotes, records = generate_review(date, cfg)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]复盘报告生成失败：{exc}[/red]")
        return
    try:
        from .storage import save_review

        save_review(date or datetime.now().strftime("%Y-%m-%d"),
                    str(path), quotes, records)
    except Exception:
        logger.exception("复盘记录 SQLite 落盘失败")
    console.print(f"[green]复盘报告已生成: {path}[/green]")


def render_scan(result) -> None:
    """以表格打印全市场异动榜单（A 股习惯：涨红跌绿）。"""

    def board(title: str, rows: list[dict], fmt: str) -> None:
        if not rows:
            return
        table = Table(title=title)
        table.add_column("代码", justify="left")
        table.add_column("名称", justify="left")
        table.add_column("最新价", justify="right")
        for col in ("涨跌幅", "量比", "换手率", "振幅"):
            table.add_column(col, justify="right")
        for r in rows:
            color = "red" if r["change_pct"] > 0 else ("green" if r["change_pct"] < 0 else "white")
            table.add_row(
                r["code"], r["name"], f"{r['price']:.2f}",
                f"[{color}]{r['change_pct']:+.2f}%[/{color}]",
                f"{r['volume_ratio']:.2f}" if r["volume_ratio"] is not None else "-",
                f"{r['turnover_rate']:.1f}%" if r["turnover_rate"] is not None else "-",
                f"{r['amplitude']:.2f}%" if r["amplitude"] is not None else "-",
            )
        console.print(table)

    board("涨幅榜", result.gainers, "+")
    board("跌幅榜", result.losers, "-")
    board("放量异动（量比 ≥ 阈值）", result.volume_spikes, "")
    board("高换手", result.hot_turnover, "")
    board("高振幅", result.wide_amplitude, "")


def run_scan(config_path: str | None) -> None:
    from .screener import ScanConfig, scan_market

    cfg = load_config(config_path)
    setup_logging(cfg.logging)
    console.print("[cyan]正在拉取全市场快照并扫描异动…[/cyan]")
    try:
        result = scan_market(cfg=ScanConfig(
            limit=cfg.scan.limit,
            exclude_st=cfg.scan.exclude_st,
            min_price=cfg.scan.min_price,
            volume_ratio=cfg.scan.volume_ratio,
            turnover_rate=cfg.scan.turnover_rate,
        ))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]扫描失败：{exc}[/red]")
        return
    render_scan(result)


def run_ipo(keyword: str | None, limit: int,
            report: bool = False, config_path: str | None = None,
            history_codes: str | None = None) -> None:
    """IPO 分析：列表 / 单只详情 / --report 近期报告 / --history 历史 IPO 分析。"""
    from .ipo import analyze_ipo, fetch_ipo_list, find_ipo

    console.print(f"[cyan]正在获取近期新股数据（{limit} 条）…[/cyan]")
    try:
        items = fetch_ipo_list(limit=limit)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]IPO 数据获取失败：{exc}[/red]")
        return

    if history_codes:
        from pathlib import Path

        from .ipo import build_ipo_history_report, fetch_ipo_history
        from .storage import load_klines

        codes = [c.strip() for c in history_codes.split(",") if c.strip()]
        records = []
        for code in codes:
            market = "hk" if len(code) == 5 else "ashare"
            try:
                rec = fetch_ipo_history(code, market)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]{code} 历史 IPO 查询失败：{exc}[/red]")
                return
            # 港股/最新价缺失时用本地 K 线补（较发行价涨幅按最新收盘算）
            if rec.get("newest_price") is None:
                rows = load_klines(code, market)
                if rows:
                    rec["newest_price"] = float(rows[-1]["close"])
                    if rec.get("issue_price"):
                        rec["newest_change"] = (
                            float(rows[-1]["close"]) / rec["issue_price"] - 1
                        ) * 100
            records.append(rec)
        html, md = build_ipo_history_report(records)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"ipo-history-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]历史 IPO 分析报告已生成: {out_path}[/green]")
        cfg = load_config(config_path)
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            ipo_dir = Path(vault) / "IPO分析"
            ipo_dir.mkdir(parents=True, exist_ok=True)
            md_path = ipo_dir / f"ipo-history-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")
        return

    if report:
        from pathlib import Path

        from .ipo import build_ipo_report

        html, md = build_ipo_report(items)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"ipo-report-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]IPO 分析报告已生成: {out_path}[/green]")
        # 导出 Markdown 到 Obsidian 库（配置了 vault 才执行）
        cfg = load_config(config_path)
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            ipo_dir = Path(vault) / "IPO分析"
            ipo_dir.mkdir(parents=True, exist_ok=True)
            md_path = ipo_dir / f"ipo-report-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")
        return

    if not keyword:
        table = Table(title="近期新股（按申购日倒序）")
        table.add_column("代码", justify="left")
        table.add_column("名称", justify="left")
        table.add_column("交易所", justify="left")
        table.add_column("申购日", justify="left")
        table.add_column("发行价", justify="right")
        table.add_column("行业PE", justify="right")
        table.add_column("募资(亿)", justify="right")
        table.add_column("状态", justify="center")
        for r in items:
            stage_style = {"待申购": "cyan", "待定价": "yellow",
                           "待上市": "magenta", "已上市": "green"}.get(r.stage(), "")
            table.add_row(
                r.code, r.name, r.market.replace("证券交易所", ""),
                r.apply_date or "-",
                f"{r.issue_price:.2f}" if r.issue_price is not None else "-",
                f"{r.industry_pe:.1f}" if r.industry_pe is not None else "-",
                f"{r.raise_funds:.2f}" if r.raise_funds is not None else "-",
                f"[{stage_style}]{r.stage()}[/{stage_style}]" if stage_style else r.stage(),
            )
        console.print(table)
        print_disclaimer()
        return

    rec = find_ipo(items, keyword)
    if rec is None:
        console.print(f"[red]未找到 {keyword}（试试新股列表里的名称或代码）[/red]")
        return

    console.print(f"[bold cyan]{rec.name}({rec.code}) IPO 分析[/bold cyan]")
    detail = Table()
    detail.add_column("项目", justify="left")
    detail.add_column("内容", justify="left")
    for label, value in (
        ("交易所", rec.market),
        ("行业", rec.industry),
        ("申购日", rec.apply_date or "-"),
        ("上市日", rec.listing_date or "-"),
        ("发行价", f"{rec.issue_price:.2f} 元" if rec.issue_price is not None else "待公布"),
        ("发行PE", f"{rec.issue_pe:.1f}" if rec.issue_pe is not None else "-"),
        ("行业PE", f"{rec.industry_pe:.1f}" if rec.industry_pe is not None else "-"),
        ("发行量", f"{rec.issue_num:,.0f} 万股" if rec.issue_num is not None else "-"),
        ("募资", f"{rec.raise_funds:.2f} 亿（计划 {rec.plan_funds:.0f} 亿）"
         if rec.raise_funds is not None and rec.plan_funds else
         (f"{rec.raise_funds:.2f} 亿" if rec.raise_funds is not None else "-")),
        ("最新价", f"{rec.newest_price:.2f} 元" if rec.newest_price is not None else "未上市"),
        ("保荐机构", rec.underwriter or "-"),
    ):
        detail.add_row(label, value)
    console.print(detail)

    console.print("[bold cyan]IPO 分析[/bold cyan]")
    for line in analyze_ipo(rec):
        console.print(f"  • {line}")
    print_disclaimer()


def run_obsidian(action: str, vault: str | None, config_path: str | None) -> None:
    """管理独立 Obsidian 知识库（init / index）。"""
    from .obsidian_vault import build_vault_index, init_vault

    cfg = load_config(config_path)
    vault_path = vault or cfg.obsidian.vault
    if not vault_path:
        console.print("[red]未配置 obsidian.vault（config.yaml），或指定 --vault 路径[/red]")
        return
    try:
        if action == "init":
            root = init_vault(vault_path, cfg.obsidian.reports_dir)
            console.print(f"[green]Obsidian 知识库已初始化: {root}[/green]")
            console.print("[dim]用 Obsidian 打开该目录即可使用（含 .obsidian 配置与复盘模板）[/dim]")
        else:  # index
            home = build_vault_index(vault_path, cfg.obsidian.reports_dir)
            console.print(f"[green]知识库索引已更新: {home}[/green]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Obsidian 操作失败：{exc}[/red]")


def run_backfill(code: str, market: str | None, config_path: str | None,
                 kline: bool, news: bool, financial: bool) -> None:
    """回填标的自上市以来的全量历史数据（行情/公告/研报/财报）。"""
    from .backfill import backfill_all

    market = market or ("hk" if len(code) == 5 else "ashare")
    if not (kline or news or financial):
        kline = news = financial = True   # 默认全量回填
    console.print(f"[cyan]正在回填 {code}（{market}）上市以来数据…[/cyan]")
    result = backfill_all(code, market, with_kline=kline, with_news=news,
                          with_financial=financial)
    for dim, info in result.items():
        if "error" in info:
            console.print(f"[red]{dim} 回填失败：{info['error']}[/red]")
        elif dim == "news":
            console.print(f"[green]{dim}：公告新增 {info['announcements']} / "
                          f"研报新增 {info['reports']}[/green]")
        else:
            console.print(f"[green]{dim}：新增 {info['new']} 条（库内共 {info['total']}）[/green]")
    console.print("[dim]提示：回填数据存于 data/ashare_monitor.db，"
                  "可用 history 命令查看上市以来分析[/dim]")


def run_history(code: str, market: str | None, config_path: str | None) -> None:
    """查看标的"自上市以来"统计（需先 backfill 入库）。"""
    from .backfill import analyze_history
    from .storage import count_klines, load_klines

    market = market or ("hk" if len(code) == 5 else "ashare")
    rows = load_klines(code, market)
    if len(rows) < 2:
        console.print(f"[yellow]{code}（{market}）暂无入库 K 线，"
                      f"请先运行: backfill {code} --market {market}[/yellow]")
        return
    try:
        h = analyze_history(rows)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]分析失败：{exc}[/red]")
        return

    console.print(f"[bold cyan]{code}（{market}）自上市以来  "
                  f"{datetime.now():%Y-%m-%d}[/bold cyan]")
    table = Table()
    table.add_column("指标", justify="left")
    table.add_column("数值", justify="right")
    table.add_row("上市首日", f"{h['first_date']}（收盘 {h['first_close']:.2f}）")
    table.add_row("交易天数", f"{h['bars']} 天（约 {h['years']} 年）")
    table.add_row("最新收盘", f"{h['latest_close']:.2f}（{h['last_date']}）")
    total = h.get("total_return_pct")
    table.add_row("上市以来涨幅", f"{total:+.2f}%" if total is not None else "-（前复权早期价格失真）")
    ann = h.get("annualized_pct")
    table.add_row("年化收益", f"{ann:+.2f}%" if ann is not None else "-")
    table.add_row("历史最高", f"{h['all_time_high']:.2f}（{h['all_time_high_date']}）")
    table.add_row("历史最低", f"{h['all_time_low']:.2f}（{h['all_time_low_date']}）")
    table.add_row("历史区间位置", f"{h['position_pct']:.1f}%（0=最低 100=最高）")
    table.add_row("距历史高点", f"{h['drawdown_pct']:+.2f}%")
    table.add_row("近一年涨跌", f"{h['year_return_pct']:+.2f}%（高 {h['year_high']:.2f}"
                                f" / 低 {h['year_low']:.2f}）")
    console.print(table)
    print_disclaimer()


def run_backtest(code: str, market: str | None, buy_date: str | None,
                 amount: float, holds: str, config_path: str | None,
                 dca: bool = False, months: int = 60,
                 detail: bool = False, compare: str = "",
                 chart: bool = False) -> None:
    """回测：单笔 / 定投 / 多标的对比 / 可视化。"""
    from .backtest import backtest, dca_backtest

    market = market or ("hk" if len(code) == 5 else "ashare")

    if compare:
        codes = [c.strip() for c in compare.split(",") if c.strip()]
        if code not in codes:
            codes.insert(0, code)
        hold = int(holds.split(",")[0])
        console.print(f"[cyan]定投对比 {codes}：每月买入 {amount:,.0f} 元，"
                      f"持有 {hold} 交易日，近 {months} 月[/cyan]")
        try:
            from .backtest import dca_compare

            results = dca_compare(codes, amount=amount, months=months, hold_days=hold)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]对比失败：{exc}[/red]")
            return
        table = Table(title=f"定投对比（持有 {hold} 交易日）")
        table.add_column("标的", justify="left")
        table.add_column("笔数", justify="right")
        table.add_column("平均", justify="right")
        table.add_column("中位", justify="right")
        table.add_column("胜率", justify="right")
        table.add_column("最好", justify="right")
        table.add_column("最差", justify="right")
        table.add_column("年化", justify="right")
        for r in results:
            if "error" in r:
                table.add_row(f"{r['code']}({r['market']})", "-", "-", "-", "-",
                              "-", "-", f"[red]{r['error'][:20]}[/red]")
                continue
            def cell(v: float, suffix: str = "%") -> str:
                style = "red" if v > 0 else ("green" if v < 0 else "")
                return f"[{style}]{v:+.2f}{suffix}[/{style}]" if style else f"{v:+.2f}{suffix}"
            table.add_row(
                f"{r['code']}({r['market']})", str(r["trades"]),
                cell(r["avg_return_pct"]), cell(r["median_return_pct"]),
                cell(r["win_rate_pct"]), cell(r["best_pct"]),
                cell(r["worst_pct"]), cell(r["avg_annualized_pct"]),
            )
        console.print(table)
        print_disclaimer()
        return

    if chart:
        hold = int(holds.split(",")[0])
        console.print(f"[cyan]生成回测可视化 {code}（{market}）："
                      f"{buy_date or '默认'} 买入，持有 {hold} 交易日[/cyan]")
        try:
            from pathlib import Path as _Path

            from .backtest import backtest_chart_data, build_backtest_html

            data = backtest_chart_data(code, market, buy_date=buy_date,
                                       hold_days=hold, amount=amount)
            html = build_backtest_html(data)
            out_dir = _Path("output")
            out_dir.mkdir(exist_ok=True)
            name = f"backtest-{code}-{data['buy']['x']}-{hold}.html"
            out_path = out_dir / name
            out_path.write_text(html, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]回测可视化失败：{exc}[/red]")
            return
        console.print(f"[green]回测可视化已生成: {out_path}[/green]")
        return

    if dca:
        try:
            hold = int(holds.split(",")[0])
        except ValueError:
            console.print("[red]--hold-days 需为整数（定投模式取第一档）[/red]")
            return
        console.print(f"[cyan]定投回测 {code}（{market}）：近 {months} 个月每月买入 "
                      f"{amount:,.0f} 元，持有 {hold} 个交易日后卖出[/cyan]")
        try:
            result = dca_backtest(code, market, amount=amount, months=months,
                                  hold_days=hold)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]定投回测失败：{exc}[/red]")
            return
        console.print(f"[bold cyan]{code} 定投统计（{result['period']}，共 {result['trades']} 笔）[/bold cyan]")
        stat = Table()
        stat.add_column("指标", justify="left")
        stat.add_column("数值", justify="right")
        stat.add_row("交易笔数", str(result["trades"]))
        for label, key, suffix in (
            ("平均收益率", "avg_return_pct", "%"),
            ("中位数收益率", "median_return_pct", "%"),
            ("胜率", "win_rate_pct", "%"),
            ("最好一笔", "best_pct", "%"),
            ("最差一笔", "worst_pct", "%"),
            ("平均年化", "avg_annualized_pct", "%"),
        ):
            val = result[key]
            style = "red" if val > 0 else ("green" if val < 0 else "")
            cell = f"[{style}]{val:+.2f}{suffix}[/{style}]" if style else f"{val:+.2f}{suffix}"
            stat.add_row(label, cell)
        console.print(stat)

        if detail:
            console.print("[bold cyan]逐笔明细[/bold cyan]")
            d = Table()
            d.add_column("买入日", justify="left")
            d.add_column("买入价", justify="right")
            d.add_column("卖出日", justify="left")
            d.add_column("卖出价", justify="right")
            d.add_column("收益率", justify="right")
            d.add_column("年化", justify="right")
            for t in result["detail"]:
                style = "red" if t["return_pct"] > 0 else ("green" if t["return_pct"] < 0 else "")
                cell = f"[{style}]{t['return_pct']:+.2f}%[/{style}]" if style else f"{t['return_pct']:+.2f}%"
                d.add_row(t["buy_date"], f"{t['buy_price']:.2f}",
                          t["sell_date"], f"{t['sell_price']:.2f}",
                          cell, f"{t['annualized_pct']:+.1f}%")
            console.print(d)
        console.print("[dim]注：每月首个交易日买入，逐笔独立不复利，未计佣金税费[/dim]")
        print_disclaimer()
        return

    try:
        hold_list = [int(h.strip()) for h in holds.split(",") if h.strip()]
    except ValueError:
        console.print("[red]--hold-days 需为逗号分隔的整数，如 60,120,250[/red]")
        return
    console.print(f"[cyan]回测 {code}（{market}）：{buy_date or '默认'} 买入 "
                  f"{amount:,.0f} 元，持有 {hold_list} 个交易日[/cyan]")
    try:
        results = backtest(code, market, buy_date=buy_date, amount=amount,
                           hold_days=hold_list)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]回测失败：{exc}[/red]")
        return

    table = Table(title=f"{code} 持有期回测")
    table.add_column("持有(交易日)", justify="right")
    table.add_column("买入日", justify="left")
    table.add_column("买入价", justify="right")
    table.add_column("卖出日", justify="left")
    table.add_column("卖出价", justify="right")
    table.add_column("金额(买→卖)", justify="right")
    table.add_column("收益率", justify="right")
    table.add_column("年化", justify="right")
    table.add_column("持有期高低", justify="right")
    for r in results:
        if r["status"] != "ok":
            table.add_row(str(r["hold_days"]), r["buy_date"], "-", "-", "-",
                          "-", "-", "-",
                          r["status"] + (f"（可持 {r.get('available')} 天）" if "available" in r else ""))
            continue
        style = "red" if r["return_pct"] > 0 else ("green" if r["return_pct"] < 0 else "")
        ret_cell = (
            f"[{style}]{r['return_pct']:+.2f}%[/{style}]"
            if style else f"{r['return_pct']:+.2f}%"
        )
        table.add_row(
            str(r["hold_days"]), r["buy_date"], f"{r['buy_price']:.2f}",
            r["sell_date"], f"{r['sell_price']:.2f}",
            f"{r['buy_amount']:,.0f}→{r['sell_amount']:,.0f}",
            ret_cell, f"{r['annualized_pct']:+.1f}%",
            f"{r['high']:.2f} / {r['low']:.2f}",
        )
    console.print(table)
    console.print("[dim]注：按整手成交（A股100/手，港股按每手），未计佣金与税费；"
                  "回测为历史价格模拟，不构成投资建议[/dim]")
    print_disclaimer()


def run_report(period: str, date: str | None, config_path: str | None) -> None:
    from .review import generate_period_report

    cfg = load_config(config_path)
    setup_logging(cfg.logging)
    console.print(f"[cyan]正在生成{period}复盘汇总报告…[/cyan]")
    try:
        path = generate_period_report(period, date, cfg)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]汇总报告生成失败：{exc}[/red]")
        return
    console.print(f"[green]汇总报告已生成: {path}[/green]")


def main() -> None:
    parser = argparse.ArgumentParser(description="A 股交易信息监控")
    parser.add_argument("--config", help="配置文件路径（默认 config.yaml）")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("monitor", help="持续监控（默认命令）")
    sub.add_parser("once", help="获取一次行情快照后退出")
    p_analyze = sub.add_parser("analyze", help="拉取个股历史数据并分析")
    p_analyze.add_argument("code", help="证券代码，如 600519 / 00700 / BTCUSDT")
    p_analyze.add_argument("--market", default="ashare",
                           choices=["ashare", "hk", "crypto"], help="市场（默认 ashare）")
    p_analyze.add_argument("--days", type=int, default=250, help="回看K线数（默认 250）")
    p_analyze.add_argument("--adjust", default="qfq",
                           choices=["qfq", "hfq", ""], help="复权方式（默认 qfq 前复权）")
    p_analyze.add_argument("--period", default="daily",
                           choices=["daily", "weekly", "monthly"],
                           help="K 线周期：日线/周线/月线（默认 daily）")
    p_advice = sub.add_parser("advice", help="规则化交易信号（结合实时行情）")
    p_advice.add_argument("code", help="证券代码，如 600519 / 00700 / BTCUSDT")
    p_advice.add_argument("--market", default="ashare",
                          choices=["ashare", "hk", "crypto"], help="市场（默认 ashare）")
    p_advice.add_argument("--days", type=int, default=120, help="回看交易日数（默认 120）")
    p_ind = sub.add_parser("indicator", help="技术指标（MACD/RSI/KDJ/BOLL）")
    p_ind.add_argument("code", help="证券代码，如 600519 / 00700 / BTCUSDT")
    p_ind.add_argument("--market", default="ashare",
                       choices=["ashare", "hk", "crypto"], help="市场（默认 ashare）")
    p_ind.add_argument("--days", type=int, default=120, help="回看K线数（默认 120）")
    p_ind.add_argument("--period", default="daily",
                       choices=["daily", "weekly", "monthly"],
                       help="K 线周期：日线/周线/月线（默认 daily）")
    p_news = sub.add_parser("news", help="公告与研报（仅 A 股，自动入库）")
    p_news.add_argument("code", nargs="?", default="", help="6 位证券代码，如 600519")
    p_news.add_argument("--days", type=int, default=90, help="研报回看天数（默认 90）")
    p_news.add_argument("--local", action="store_true", help="仅读取数据库，不联网")
    p_news.add_argument("--watchlist", action="store_true", help="批量采集全部 A 股自选股入库")
    p_fin = sub.add_parser("financial", help="财报分析（A 股人民币 / 港股港元，东财接口）")
    p_fin.add_argument("code", help="证券代码，如 600519 / 01211")
    p_fin.add_argument("--periods", type=int, default=6, help="回看报告期数（默认 6）")
    p_fin.add_argument("--market", default="ashare", choices=["ashare", "hk"],
                       help="市场（默认 ashare）")
    p_ipo = sub.add_parser("ipo", help="IPO 公司分析（近期新股列表 / 单只详情 / --report 报告）")
    p_ipo.add_argument("keyword", nargs="?", default="", help="新股代码或名称（缺省显示列表）")
    p_ipo.add_argument("--limit", type=int, default=30, help="列表条数（默认 30）")
    p_ipo.add_argument("--report", action="store_true",
                       help="生成 IPO 分析报告（HTML + Obsidian Markdown）")
    p_ipo.add_argument("--history", metavar="CODES",
                       help="历史 IPO 发行分析（逗号分隔代码，如 002594,01211）")
    p_export = sub.add_parser("export", help="导出复盘报告（Obsidian Markdown）")
    p_export.add_argument("--date", help="复盘日期 YYYY-MM-DD，默认今天")
    p_export.add_argument("--obsidian", action="store_true",
                          help="导出 Markdown 到 Obsidian 库（需 config.obsidian.vault）")
    p_ob = sub.add_parser("obsidian", help="管理独立 Obsidian 知识库")
    p_ob.add_argument("action", choices=["init", "index"],
                      help="init=初始化库结构；index=重建首页索引")
    p_ob.add_argument("--vault", help="vault 路径（默认取 config.obsidian.vault）")
    p_backfill = sub.add_parser("backfill", help="回填上市以来全量数据（行情/公告/研报/财报）")
    p_backfill.add_argument("code", help="证券代码，如 002594 / 01211")
    p_backfill.add_argument("--market", choices=["ashare", "hk"],
                            help="市场（缺省按代码位数推断）")
    p_backfill.add_argument("--kline", action="store_true", help="仅回填日 K")
    p_backfill.add_argument("--news", action="store_true", help="仅回填公告/研报")
    p_backfill.add_argument("--financial", action="store_true", help="仅回填财报")
    p_history = sub.add_parser("history", help="上市以来统计（需先 backfill）")
    p_history.add_argument("code", help="证券代码，如 002594 / 01211")
    p_history.add_argument("--market", choices=["ashare", "hk"],
                           help="市场（缺省按代码位数推断）")
    p_bt = sub.add_parser("backtest", help="持有期回测（买入日/金额/持有交易日数）")
    p_bt.add_argument("code", help="证券代码，如 002594 / 01211 / BTCUSDT")
    p_bt.add_argument("--market", choices=["ashare", "hk", "crypto"],
                      help="市场（缺省按代码位数推断）")
    p_bt.add_argument("--buy-date", default="", help="买入日期 YYYY-MM-DD（默认最近交易日）")
    p_bt.add_argument("--amount", type=float, default=100000.0, help="买入金额（元，默认 100000）")
    p_bt.add_argument("--hold-days", default="60,120,250",
                      help="持有交易日数，逗号分隔多档（默认 60,120,250）")
    p_bt.add_argument("--dca", action="store_true",
                      help="定投模式：每月首个交易日买入固定金额，持有统计")
    p_bt.add_argument("--months", type=int, default=60, help="定投回看月数（默认 60）")
    p_bt.add_argument("--detail", action="store_true", help="定投模式显示逐笔明细")
    p_bt.add_argument("--compare", default="",
                      help="多标的定投对比，逗号分隔（如 002594,01211）")
    p_bt.add_argument("--chart", action="store_true",
                      help="生成单笔回测 K 线可视化 HTML（含买卖点标注）")
    p_review = sub.add_parser("review", help="生成复盘报告（默认今天；--backfill 回填历史）")
    p_review.add_argument("--date", help="复盘日期 YYYY-MM-DD，默认今天")
    p_review.add_argument("--backfill", metavar="START",
                          help="回填历史复盘：起始日期 YYYY-MM-DD（用本地 klines 库，需先 backfill --kline）")
    p_review.add_argument("--end", help="回填结束日期 YYYY-MM-DD，默认昨天")
    sub.add_parser("scan", help="全市场异动扫描（涨幅/跌幅/放量/换手/振幅榜）")
    p_report = sub.add_parser("report", help="生成周/月/年复盘汇总报告")
    p_report.add_argument("--weekly", action="store_true", help="周报（默认）")
    p_report.add_argument("--monthly", action="store_true", help="月报")
    p_report.add_argument("--yearly", action="store_true", help="年报（近 365 天）")
    p_report.add_argument("--date", help="周期结束日期 YYYY-MM-DD，默认今天")

    args = parser.parse_args()
    if args.command == "once":
        run_once(args.config)
    elif args.command == "analyze":
        run_analyze(args.code, args.days, args.adjust, args.market, args.period)
    elif args.command == "advice":
        run_advice(args.code, args.market, args.days, args.config)
    elif args.command == "indicator":
        run_indicator(args.code, args.market, args.days, args.config, args.period)
    elif args.command == "news":
        if args.watchlist:
            run_news("", "ashare", args.days, args.config, watchlist=True)
        elif not args.code:
            parser.error("news 需要提供 code，或用 --watchlist 批量采集")
        else:
            run_news(args.code, "ashare", args.days, args.config,
                     local_only=args.local)
    elif args.command == "financial":
        run_financial(args.code, args.periods, args.market)
    elif args.command == "ipo":
        run_ipo(args.keyword, args.limit, report=args.report,
                config_path=args.config, history_codes=args.history)
    elif args.command == "export":
        run_review(args.date, args.config)
        console.print("[dim]提示：Obsidian 导出由 config.obsidian.vault 控制，"
                      "review 生成时自动执行[/dim]")
    elif args.command == "obsidian":
        run_obsidian(args.action, args.vault, args.config)
    elif args.command == "backfill":
        run_backfill(args.code, args.market, args.config,
                     args.kline, args.news, args.financial)
    elif args.command == "history":
        run_history(args.code, args.market, args.config)
    elif args.command == "backtest":
        run_backtest(args.code, args.market, args.buy_date or None,
                     args.amount, args.hold_days, args.config,
                     dca=args.dca, months=args.months, detail=args.detail,
                     compare=args.compare, chart=args.chart)
    elif args.command == "review":
        run_review(args.date, args.config,
                   backfill_start=args.backfill, backfill_end=args.end)
    elif args.command == "scan":
        run_scan(args.config)
    elif args.command == "report":
        period = "yearly" if args.yearly else ("monthly" if args.monthly else "weekly")
        run_report(period, args.date, args.config)
    else:
        run_monitor(args.config)


if __name__ == "__main__":
    main()
