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
    """渲染公告/研报表（重大事项标红 ★）。"""
    from .announcements import is_major

    console.print(f"[bold cyan]{code} 最新公告（{len(anns)} 条，★=重大事项）[/bold cyan]")
    ann_table = Table()
    ann_table.add_column("日期", justify="left")
    ann_table.add_column("标题", justify="left", overflow="fold")
    ann_table.add_column("链接", justify="left", overflow="fold")
    for a in anns:
        title = a["title"]
        if is_major(title):
            title = f"[bold red]★ {title}[/bold red]"
        ann_table.add_row(a["date"], title, a["url"])
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


def run_portfolio(codes: str, weights: str | None, amount: float,
                  months: int, hold_days: int, config_path: str | None,
                  report: bool = False) -> None:
    """组合定投回测：多标的按权重每月定投。"""
    from pathlib import Path

    from .backtest import build_portfolio_report, dca_portfolio

    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    w_list = ([float(x) for x in weights.split(",")]
              if weights else None)
    if w_list and len(w_list) != len(code_list):
        console.print("[red]权重数量与标的不一致[/red]")
        return
    console.print(f"[cyan]组合定投回测 {code_list}（权重 "
                  f"{w_list or ['等权'] * len(code_list)}，每月 {amount:,.0f} 元，"
                  f"持有 {hold_days} 交易日，近 {months} 月）…[/cyan]")
    try:
        result = dca_portfolio(code_list, w_list, amount=amount,
                               months=months, hold_days=hold_days)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]组合回测失败：{exc}[/red]")
        return
    pf = result["portfolio"]
    table = Table(title="组合定投对比（持有 %d 交易日）" % hold_days)
    table.add_column("标的", justify="left")
    table.add_column("权重", justify="right")
    table.add_column("笔数", justify="right")
    table.add_column("平均收益", justify="right")
    table.add_column("胜率", justify="right")
    table.add_column("最好", justify="right")
    table.add_column("最差", justify="right")
    table.add_column("累计/年化", justify="right")
    for row in [("组合", "100%", pf["trades"], pf["avg_return_pct"],
                 pf["win_rate_pct"], pf["best_pct"], pf["worst_pct"],
                 pf["cum_return_pct"])] + [
        (it["code"], f"{it['weight_pct']:.0f}%", it["trades"],
         it["avg_return_pct"], it["win_rate_pct"], it["best_pct"],
         it["worst_pct"], it["avg_annualized_pct"])
        for it in result["items"]
    ]:
        def cell(v: float) -> str:
            style = "red" if v > 0 else ("green" if v < 0 else "")
            return f"[{style}]{v:+.1f}%[/{style}]" if style else f"{v:+.1f}%"
        table.add_row(
            str(row[0]), str(row[1]), str(row[2]),
            cell(row[3]), f"{row[4]:.0f}%",
            cell(row[5]), cell(row[6]), cell(row[7]),
        )
    console.print(table)
    console.print(f"[dim]组合区间 {pf['period']} · 累计收益（复利）{pf['cum_return_pct']:+.1f}%[/dim]")
    print_disclaimer()

    if report:
        html, md = build_portfolio_report(result, amount=amount,
                                          hold_days=hold_days, months=months)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"portfolio-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]组合回测报告已生成: {out_path}[/green]")
        cfg = load_config(config_path)
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "策略验证"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"portfolio-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


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
        if chart:  # --report 复用 --chart 开关输出对比报告
            from pathlib import Path

            from .backtest import build_compare_report

            html, md = build_compare_report(
                results, amount=amount, hold_days=hold, months=months,
            )
            out_dir = Path("output")
            out_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            out_path = out_dir / f"backtest-compare-{today}.html"
            out_path.write_text(html, encoding="utf-8")
            console.print(f"[green]定投对比报告已生成: {out_path}[/green]")
            cfg = load_config(config_path)
            vault = str(getattr(cfg.obsidian, "vault", "")).strip()
            if vault:
                vdir = Path(vault) / "策略验证"
                vdir.mkdir(parents=True, exist_ok=True)
                md_path = vdir / f"backtest-compare-{today}.md"
                md_path.write_text(md, encoding="utf-8")
                console.print(f"[dim]Obsidian: {md_path}[/dim]")
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


def run_verify(code: str, market: str, rule: str | None, days: int,
               forward: int, config_path: str | None,
               report: bool = False) -> None:
    """信号命中率验证：基于回填 K 线回测价格规则的触发后表现。"""
    from pathlib import Path

    from .verify import RULES, build_verify_report, run_verify

    market = market or ("hk" if len(code) == 5 else "ashare")
    console.print(f"[cyan]正在验证 {code}（{market}）规则命中率"
                  f"（近 {days} 日，触发后 {forward} 交易日）…[/cyan]")
    try:
        results = run_verify(code, market, rule, days, forward)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]命中率验证失败：{exc}[/red]")
        return

    table = Table(title=f"{code} 信号命中率（{forward} 交易日观察）")
    table.add_column("规则", justify="left")
    table.add_column("信号数", justify="right")
    table.add_column("方向命中率", justify="right")
    table.add_column("平均收益", justify="right")
    table.add_column("中位数", justify="right")
    table.add_column("最好", justify="right")
    table.add_column("最差", justify="right")
    for r in results:
        style = ("red" if (r["win_rate"] or 0) >= 60 else
                 ("green" if (r["win_rate"] or 0) <= 40 else ""))
        win = f"{r['win_rate']:.1f}%" if r["win_rate"] is not None else "-"
        win_cell = f"[{style}]{win}[/{style}]" if style else win
        table.add_row(
            r["label"], str(r["signals"]), win_cell,
            f"{r['avg_return']:+.2f}%" if r["avg_return"] is not None else "-",
            f"{r['median_return']:+.2f}%" if r["median_return"] is not None else "-",
            f"{r['best']:+.2f}%" if r["best"] is not None else "-",
            f"{r['worst']:+.2f}%" if r["worst"] is not None else "-",
        )
    console.print(table)
    rule_hint = ", ".join(
        "{}={}".format(k, v["label"]) for k, v in RULES.items()
    )
    console.print(f"[dim]可用规则: {rule_hint}[/dim]")
    print_disclaimer()

    if report:
        html, md = build_verify_report(code, market, results)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"verify-{code}-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]命中率验证报告已生成: {out_path}[/green]")
        cfg = load_config(config_path)
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "策略验证"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"verify-{code}-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_site(code: str | None, config_path: str | None,
             report: bool = False) -> None:
    """官方网站链接档案 + 官网公告监控。"""
    from pathlib import Path

    from .site import (
        build_site_report,
        fetch_site_notices,
        site_links,
    )

    cfg = load_config(config_path)
    targets = []
    for item in cfg.watchlist:
        c = str(item["code"])
        if code and c != code:
            continue
        targets.append((c, str(item.get("name", c))))
    if not targets:
        console.print("[yellow]自选股为空或指定代码不在自选股[/yellow]")
        return

    links_list, all_notices = [], []
    console.print("[cyan]正在聚合官方链接并抓取公告…[/cyan]")
    for c, name in targets:
        sl = site_links(cfg, c, name)
        links_list.append(sl)
        notices, status = fetch_site_notices(sl)
        if notices:
            all_notices.extend(notices)
            console.print(f"[dim]{name}({c})：抓取到 {len(notices)} 条官网公告[/dim]")
        elif sl.notice_url:
            console.print(f"[yellow]{name}({c})：{status}[/yellow]")
        else:
            console.print(f"[dim]{name}({c})：未配置公告页（官网 {sl.website or '-'}）[/dim]")

    table = Table(title="官方网站链接档案")
    table.add_column("标的", justify="left")
    table.add_column("官网", justify="left", overflow="fold")
    table.add_column("公告页", justify="left", overflow="fold")
    for sl in links_list:
        table.add_row(f"{sl.name}({sl.code})", sl.website or "-",
                      sl.notice_url or "-")
    console.print(table)
    if all_notices:
        ntable = Table(title="官网公告（可解析部分）")
        ntable.add_column("日期", justify="left")
        ntable.add_column("标的", justify="left")
        ntable.add_column("标题", justify="left", overflow="fold")
        for n in all_notices[:15]:
            ntable.add_row(n.date, f"{n.name}({n.code})", n.title)
        console.print(ntable)
    else:
        console.print("[yellow]官网公告多为 JS 动态加载，自动抓取不可用"
                      "（请从公告页链接人工查看；权威公告以东财公告为准）[/yellow]")
    print_disclaimer()

    if report:
        html, md = build_site_report(links_list, all_notices)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"site-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]官网档案报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "官网公告"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"site-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def _corp_metric_run(name: str, cfg, fetch_fn, save_fn, report_fn,
                     report_dir: str, console_title: str,
                     cols: list[str], row_fn, save: bool = True,
                     push_text: str | None = None, push: bool = False):
    """公司信号类命令的通用执行器（终端表 + 入库 + 报告）。"""
    import os
    from pathlib import Path

    console.print(f"[cyan]{console_title}…[/cyan]")
    try:
        rows = fetch_fn()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]获取失败：{exc}[/red]")
        return
    if not rows:
        console.print("[yellow]无数据[/yellow]")
    else:
        table = Table(title=console_title)
        for c in cols:
            table.add_column(c, justify="right" if c not in ("标的",) else "left")
        for r in rows:
            table.add_row(*row_fn(r))
        console.print(table)
    print_disclaimer()
    if save and save_fn and rows:
        added = save_fn(rows)
        console.print(f"[dim]入库新增 {added} 条[/dim]")
    if push and push_text and rows:
        webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
        if webhook:
            from .notify import WebhookNotifier

            lines = [push_text]
            for r in rows[:8]:
                lines.append(str(r))
            WebhookNotifier(webhook).send_text("\n".join(lines))
            console.print("[green]已推送 webhook[/green]")
    if report_fn:
        html, md = report_fn(rows)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"{name}-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]{name} 报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / report_dir
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"{name}-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_insider(code: str | None, config_path: str | None, days: int = 30,
                report: bool = False, push: bool = False) -> None:
    """增减持与回购监控。"""
    from .corp_events import (
        build_corp_report,
        load_saved_events,
        save_corp_events,
        scan_corp_events,
    )

    cfg = load_config(config_path)

    def _fetch():
        rows = scan_corp_events(cfg, codes=[code] if code else None)
        return [r for r in rows if r.date >= (
            datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")]

    def _row(r):
        return (f"{r.name}({r.code})", r.date, r.event_type, r.title)

    _corp_metric_run(
        "insider", cfg, _fetch, save_corp_events, build_corp_report,
        "增减持回购", f"增减持与回购事件（近 {days} 天）",
        ["标的", "日期", "类型", "标题"],
        _row, push_text="增减持/回购事件", push=push,
    )
    if report:
        pass  # 报告已在通用执行器生成


def run_pledge(code: str | None, config_path: str | None, days: int = 7,
               report: bool = False, push: bool = False) -> None:
    """股权质押监控。"""
    from .pledge import build_pledge_report, scan_watchlist_pledges

    cfg = load_config(config_path)

    def _fetch():
        rows = scan_watchlist_pledges(cfg, days=days)
        return [r for r in rows if not code or r.code == code]

    def _row(r):
        return (f"{r.name}({r.code})", r.announce_date, r.pledger,
                f"{r.pledge_shares / 1e4:.0f} 万股" if r.pledge_shares else "-",
                f"{r.ratio:.2f}%" if r.ratio is not None else "-")

    _corp_metric_run(
        "pledge", cfg, _fetch, None, build_pledge_report,
        "股权质押", f"股权质押公告（近 {days} 天）",
        ["标的", "公告日", "出质人", "质押数量", "占比"],
        _row, push_text="股权质押", push=push,
    )


def run_rating(code: str | None, config_path: str | None, days: int = 30,
               report: bool = False, push: bool = False) -> None:
    """券商研报监控。"""
    from .rating import build_rating_report, save_ratings, scan_ratings

    cfg = load_config(config_path)

    def _fetch():
        return scan_ratings(cfg, codes=[code] if code else None, days=days)

    def _row(r):
        return (f"{r.name}({r.code})", r.date, r.org, r.title[:30],
                f"{r.eps_this_year:.2f}" if r.eps_this_year is not None else "-")

    _corp_metric_run(
        "rating", cfg, _fetch, save_ratings, build_rating_report,
        "研报评级", f"券商研报（近 {days} 天）",
        ["标的", "日期", "机构", "标题", "EPS预测"],
        _row, push_text="券商研报", push=push,
    )


def run_lhb(code: str | None, config_path: str | None, days: int = 10,
            report: bool = False, push: bool = False) -> None:
    """龙虎榜监控。"""
    from .lhb import build_lhb_report, scan_lhb

    cfg = load_config(config_path)

    def _fetch():
        rows = scan_lhb(cfg, days=days)
        return [r for r in rows if not code or r.code == code]

    def _row(r):
        return (f"{r.name}({r.code})", r.date,
                f"{r.change_pct:+.2f}%" if r.change_pct is not None else "-",
                r.reason[:30])

    _corp_metric_run(
        "lhb", cfg, _fetch, None, build_lhb_report,
        "龙虎榜", f"龙虎榜（近 {days} 天）",
        ["标的", "日期", "涨跌幅", "上榜原因"],
        _row, push_text="龙虎榜", push=push,
    )


def run_north(code: str | None, config_path: str | None,
              report: bool = False, push: bool = False) -> None:
    """北向持股监控。"""
    from .north import build_north_report, scan_watchlist_north

    cfg = load_config(config_path)

    def _fetch():
        data = scan_watchlist_north(cfg, codes=[code] if code else None)
        return data

    def _rows(data):
        flat = []
        for c, rows in data.items():
            if rows:
                flat.append(rows[0])
        return flat

    rows = _fetch()
    flat = _rows(rows)
    if not flat:
        console.print("[yellow]无北向持股数据[/yellow]")
    else:
        table = Table(title="北向持股（自选股）")
        table.add_column("代码", justify="left")
        table.add_column("日期", justify="right")
        table.add_column("持股(亿股)", justify="right")
        table.add_column("占A股%", justify="right")
        table.add_column("今日增持(万股)", justify="right")
        for r in flat:
            add = (f"{r.today_add / 1e4:.0f}" if r.today_add is not None else "-")
            table.add_row(r.code, r.date,
                          f"{r.hold_shares / 1e8:.2f}" if r.hold_shares else "-",
                          f"{r.hold_ratio:.2f}" if r.hold_ratio is not None else "-",
                          add)
        console.print(table)
    print_disclaimer()
    if report:
        html, md = build_north_report(rows)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"north-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]north 报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "北向持股"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"north-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_block(code: str | None, config_path: str | None, days: int = 10,
              report: bool = False, push: bool = False) -> None:
    """大宗交易监控。"""
    from .block import build_block_report, scan_block_trades

    cfg = load_config(config_path)

    def _fetch():
        rows = scan_block_trades(cfg, days=days)
        return [r for r in rows if not code or r.code == code]

    def _row(r):
        return (f"{r.name}({r.code})", r.date,
                f"{r.price:.2f}" if r.price is not None else "-",
                f"{r.premium:+.2f}%" if r.premium is not None else "-",
                f"{r.amount / 1e8:.2f} 亿" if r.amount else "-")

    _corp_metric_run(
        "block", cfg, _fetch, None, build_block_report,
        "大宗交易", f"大宗交易（近 {days} 天）",
        ["标的", "日期", "成交价", "折溢率", "成交额"],
        _row, push_text="大宗交易", push=push,
    )


def run_valuation(code: str | None, config_path: str | None, years: int = 5,
                  report: bool = False, push: bool = False) -> None:
    """估值分位监控。"""
    from .valuation import (
        _zone,
        build_valuation_report,
        scan_watchlist_valuation,
    )

    cfg = load_config(config_path)

    def _fetch():
        rows = scan_watchlist_valuation(cfg, years=years)
        return [r for r in rows if not code or r.code == code]

    def _row(r):
        return (f"{r.name}({r.code})", r.date,
                f"{r.close:.2f}" if r.close is not None else "-",
                f"{r.pe_ttm:.1f} ({_zone(r.pe_pct)})" if r.pe_ttm is not None else "-",
                f"{r.pe_pct:.0f}%" if r.pe_pct is not None else "-",
                f"{r.pb_mrq:.2f} ({_zone(r.pb_pct)})" if r.pb_mrq is not None else "-")

    _corp_metric_run(
        "valuation", cfg, _fetch, None,
        lambda rows: build_valuation_report(rows, years),
        "估值分位", f"估值分位（近 {years} 年）",
        ["标的", "日期", "收盘", "PE(TTM)", "PE分位", "PB分位"],
        _row, push_text="估值分位", push=push,
    )


def run_sector(code: str | None, config_path: str | None,
               report: bool = False, push: bool = False) -> None:
    """月度产销快报（行业景气先行指标）。"""
    from .sector import build_sales_report, save_sales, scan_sales

    cfg = load_config(config_path)

    def _fetch():
        return scan_sales(cfg, codes=[code] if code else None)

    def _row(r):
        return (f"{r.name}({r.code})", r.month,
                f"{r.sales:.2f} {r.sales_unit}" if r.sales is not None
                else f"（{r.raw_sales or '未提取'}）",
                r.title[:30])

    _corp_metric_run(
        "sector", cfg, _fetch, save_sales, build_sales_report,
        "产销快报", "月度产销快报",
        ["标的", "报表月", "销量", "公告"],
        _row, push_text="产销快报", push=push,
    )


def run_gov(code: str | None, config_path: str | None, days: int = 30,
            report: bool = False, push: bool = False) -> None:
    """政府侧企业动态：中标/拿地/补助/税收优惠公告。"""
    import os
    from pathlib import Path

    from .gov import (
        GOV_KEYWORDS,
        build_gov_report,
        scan_government_dynamics,
    )

    cfg = load_config(config_path)
    codes = [code] if code else None
    console.print(f"[cyan]正在扫描政府相关公告（近 {days} 天）…[/cyan]")
    try:
        items = scan_government_dynamics(cfg, codes=codes, limit=30)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]政府动态获取失败：{exc}[/red]")
        return
    if not items:
        console.print(f"[yellow]近期自选股无政府相关公告[/yellow]")
    else:
        cat_color = {"招投标": "cyan", "拿地": "red",
                     "补助补贴": "green", "资质税收": "yellow"}
        table = Table(title=f"政府侧企业动态（近 {days} 天）")
        table.add_column("日期", justify="left")
        table.add_column("标的", justify="left")
        table.add_column("分类", justify="left")
        table.add_column("公告", justify="left", overflow="fold")
        for x in items:
            style = cat_color.get(x.category, "")
            cat = f"[{style}]{x.category}[/{style}]" if style else x.category
            table.add_row(x.date, f"{x.name}({x.code})", cat, x.title)
        console.print(table)
    console.print(f"[dim]关键词: {', '.join(GOV_KEYWORDS)}[/dim]")
    print_disclaimer()

    if push and items:
        webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
        if webhook:
            from .notify import WebhookNotifier

            lines = [f"政府动态（近 {days} 天）"]
            for x in items[:8]:
                lines.append(f"{x.date} {x.name} {x.category}: {x.title[:40]}")
            WebhookNotifier(webhook).send_text("\n".join(lines))
            console.print("[green]已推送 webhook[/green]")

    if report:
        html, md = build_gov_report(items, days)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"gov-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]政府动态报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "政府动态"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"gov-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_profile(code: str, config_path: str | None,
                report: bool = False) -> None:
    """公司档案：工商信息 + 股权结构。"""
    from pathlib import Path

    from .holders import fetch_top10
    from .profile import (
        build_profile_report,
        fetch_profile,
        infer_controller,
    )

    cfg = load_config(config_path)
    if not code:
        console.print("[red]请指定股票代码：profile 002594[/red]")
        return
    market = "hk" if len(code) == 5 and code.isdigit() else "ashare"
    console.print(f"[cyan]正在获取 {code} 公司档案…[/cyan]")
    p = fetch_profile(code, market)
    holders, report_date = [], ""
    try:
        holders, report_date = fetch_top10(code, market)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]股权结构获取失败：{exc}[/yellow]")

    # 终端输出
    console.print(f"[bold cyan]{p.full_name or p.name or code}（{code}）[/bold cyan]")
    if p.legal_person:
        console.print(
            f"  法人: {p.legal_person} | 注册资金: "
            f"{p.reg_capital / 10000:.2f} 亿" if p.reg_capital and p.reg_capital >= 10000
            else f"  法人: {p.legal_person} | 注册资金: {p.reg_capital:.0f} 万"
            if p.reg_capital else f"  法人: {p.legal_person}"
        )
        console.print(
            f"  成立: {p.founded} | 上市: {p.listed} | 行业: {p.industry}"
        )
        console.print(f"  注册地: {p.reg_address}")
        if p.main_biz:
            console.print(f"  主营: {p.main_biz[:80]}")
    for err in p.errors:
        console.print(f"[yellow]  ⚠ {err}[/yellow]")
    if holders:
        total = sum(h.ratio for h in holders if h.ratio is not None)
        controller = infer_controller(holders)
        console.print(f"[bold cyan]股权结构（十大股东合计 {total:.1f}%）[/bold cyan]")
        table = Table()
        table.add_column("名次", justify="right")
        table.add_column("股东", justify="left")
        table.add_column("占比", justify="right")
        table.add_column("变动", justify="left")
        for h in holders[:8]:
            table.add_row(str(h.rank), h.name,
                          f"{h.ratio:.2f}%" if h.ratio is not None else "-",
                          h.change)
        console.print(table)
        if controller:
            console.print(f"[cyan]疑似实控人（推断）: {controller}[/cyan]")
    print_disclaimer()

    if report:
        html, md = build_profile_report(p, holders, report_date)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"profile-{code}-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]公司档案报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "公司档案"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"profile-{code}-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_litigation(code: str | None, config_path: str | None,
                   days: int = 365, report: bool = False,
                   push: bool = False) -> None:
    """诉讼监控：自选股（或指定代码）的重大诉讼披露。"""
    import os
    from pathlib import Path

    from .litigation import (
        build_litigation_report,
        load_saved_lawsuits,
        save_lawsuits,
        scan_watchlist_lawsuits,
    )

    cfg = load_config(config_path)
    console.print(f"[cyan]正在拉取近 {days} 天全市场重大诉讼披露…[/cyan]")
    try:
        rows = scan_watchlist_lawsuits(cfg, days=days)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]诉讼数据获取失败：{exc}[/red]")
        return
    if code:
        rows = [r for r in rows if r.code == code]
    if not rows:
        console.print(f"[yellow]近 {days} 天自选股无重大诉讼披露（未达披露标准 = 正常）[/yellow]")
    else:
        table = Table(title=f"自选股重大诉讼披露（近 {days} 天）")
        table.add_column("代码", justify="left")
        table.add_column("简称", justify="left")
        table.add_column("统计区间", justify="left")
        table.add_column("次数", justify="right")
        table.add_column("金额", justify="right")
        for r in rows:
            amt = (f"{r.amount / 10000:.2f} 亿" if r.amount and r.amount >= 10000
                   else (f"{r.amount:.0f} 万" if r.amount is not None else "-"))
            table.add_row(r.code, r.name, r.period, str(r.count), amt)
        console.print(table)
    print_disclaimer()

    # 入库去重
    added = save_lawsuits(rows)
    console.print(f"[dim]入库新增 {added} 条[/dim]")

    if push and rows:
        webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
        if webhook:
            from .notify import WebhookNotifier

            lines = ["诉讼监控（近 %d 天）" % days]
            for r in rows:
                amt = (f"{r.amount / 10000:.2f} 亿" if r.amount and r.amount >= 10000
                       else (f"{r.amount:.0f} 万" if r.amount is not None else "-"))
                lines.append(f"{r.name}({r.code}) {r.count} 次，{amt}")
            WebhookNotifier(webhook).send_text("\n".join(lines))
            console.print("[green]已推送 webhook[/green]")

    if report:
        html, md = build_litigation_report(rows, days)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"litigation-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]诉讼监控报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "法律风险"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"litigation-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_hf(code: str, config_path: str | None, org_override: str | None,
           company_override: str | None, limit: int = 10,
           report: bool = False, push: bool = False) -> None:
    """Hugging Face 监测：公司 HF 模型 + 收录论文。"""
    import os
    from pathlib import Path

    from .hf import (
        build_hf_report,
        fetch_models,
        fetch_papers,
        orgs_for,
    )

    cfg = load_config(config_path)
    if not code:
        console.print("[red]请指定股票代码：hf 00700[/red]")
        return
    org, company = orgs_for(cfg, code)
    if org_override:
        org = org_override
    if company_override:
        company = company_override
    stock_name = code
    for item in cfg.watchlist:
        if str(item["code"]) == code:
            stock_name = str(item.get("name", code))
            break
    console.print(f"[cyan]正在获取 {stock_name}({code}) HF 数据"
                  f"（组织 {'无' if not org else org}，论文检索 {company or code}）…[/cyan]")
    models, papers = [], []
    try:
        models = fetch_models(org, limit=limit)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]HF 模型获取失败：{exc}[/yellow]")
    try:
        papers = fetch_papers(company or code, limit=limit)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]HF 论文获取失败：{exc}[/yellow]")

    if models:
        table = Table(title=f"{stock_name} HF 最新模型（组织 {org}）")
        table.add_column("模型", justify="left")
        table.add_column("更新", justify="right")
        table.add_column("下载", justify="right")
        table.add_column("点赞", justify="right")
        table.add_column("任务", justify="left")
        for m in models:
            table.add_row(m.id, m.last_modified, f"{m.downloads:,}",
                          str(m.likes), m.pipeline_tag or "-")
        console.print(table)
    else:
        console.print(f"[yellow]{stock_name} 无 HF 组织模型数据"
                      "（可用 --org 指定组织，如 --org Qwen）[/yellow]")
    if papers:
        console.print(f"[bold cyan]HF 收录论文（{company or code}）[/bold cyan]")
        for p in papers[:6]:
            console.print(f"  {p.published} {p.title[:60]} | {p.authors[:30]}")
    print_disclaimer()

    if push:
        webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
        if webhook:
            from .notify import WebhookNotifier

            lines = [f"HF 监测 {stock_name}({code})"]
            for m in models[:5]:
                lines.append(f"模型: {m.id}（下载 {m.downloads:,}）")
            for p in papers[:5]:
                lines.append(f"论文: {p.published} {p.title[:45]}")
            WebhookNotifier(webhook).send_text("\n".join(lines))
            console.print("[green]已推送 webhook[/green]")

    if report:
        html, md = build_hf_report(
            code, stock_name, org, company or code, models, papers,
        )
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"hf-{code}-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]HF 监测报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "公司模型"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"hf-{code}-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_arxiv(code: str, config_path: str | None, name_override: str | None,
              days: int = 14600, limit: int = 20,
              report: bool = False, push: bool = False) -> None:
    """arXiv 论文监测：以指定股票代码对应公司为署名单位的论文（默认覆盖近 40 年）。"""
    import os
    from pathlib import Path

    from .arxiv import (
        build_arxiv_report,
        company_aliases,
        fetch_company_papers,
    )

    cfg = load_config(config_path)
    if not code:
        console.print("[red]请指定股票代码：arxiv 002594[/red]")
        return
    company, aliases = company_aliases(cfg, code)
    if name_override:
        company, aliases = name_override, [name_override]
    if not company:
        console.print("[yellow]未内置该公司英文名映射，可用 --name 指定英文名"
                      "（如 arxiv 002594 --name BYD）[/yellow]")
        return
    stock_name = code
    for item in cfg.watchlist:
        if str(item["code"]) == code:
            stock_name = str(item.get("name", code))
            break
    from .arxiv import _human_days

    console.print(f"[cyan]正在检索署名单位含「{company}」的 arXiv 论文"
                  f"（{_human_days(days)}）…[/cyan]")
    try:
        papers = fetch_company_papers(company, aliases,
                                      max_results=limit, days=days)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]arXiv 查询失败：{exc}[/red]")
        return
    if not papers:
        console.print(f"[yellow]{_human_days(days)}未发现以 {company} 为署名单位的论文[/yellow]")
    else:
        table = Table(title=f"{stock_name}({code}) 公司署名论文（arXiv）")
        table.add_column("日期", justify="left")
        table.add_column("标题", justify="left", overflow="fold")
        table.add_column("署名单位", justify="left", overflow="fold")
        for p in papers[:limit]:
            table.add_row(p.published, p.title, p.affiliation[:50])
        console.print(table)
        for p in papers[:3]:
            console.print(f"[dim]  └─ {p.link} | {p.authors[:60]}[/dim]")
    print_disclaimer()

    if push and papers:
        webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
        if webhook:
            from .notify import WebhookNotifier

            lines = [f"{stock_name}({code}) 公司署名论文（arXiv）"]
            for p in papers[:5]:
                lines.append(f"{p.published} {p.title[:50]}")
            WebhookNotifier(webhook).send_text("\n".join(lines))
            console.print("[green]已推送 webhook[/green]")

    if report:
        html, md = build_arxiv_report(papers, code, stock_name, company, days)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"arxiv-{code}-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]论文监测报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "公司论文"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"arxiv-{code}-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_doctor(code: str, config_path: str | None,
               report: bool = False) -> None:
    """个股全方位体检：行情/技术/基本面/筹码/资金/事件/择时 一键汇总评分。"""
    from pathlib import Path

    from .doctor import build_doctor_report, run_doctor as _run_doctor

    cfg = load_config(config_path)
    if not code:
        console.print("[red]请指定股票代码：doctor 002594[/red]")
        return
    market = "hk" if len(code) == 5 and code.isdigit() else "ashare"
    name = code
    for item in cfg.watchlist:
        if str(item["code"]) == code:
            name = str(item.get("name", code))
            break
    console.print(f"[cyan]正在体检 {name}({code})…[/cyan]")
    data = _run_doctor(code, market, name)

    verdict_color = {"强势": "red", "中性": "yellow", "谨慎": "green"}
    vc = verdict_color.get(data["verdict"], "")
    total = data["total"]
    total_str = f"[{vc} bold]{total} {data['verdict']}[/{vc} bold]" if total is not None else "无法评分"
    console.print(f"[bold cyan]{name}({code}) 综合评分：{total_str}[/bold cyan]")
    table = Table()
    table.add_column("维度", justify="left")
    table.add_column("评分", justify="right")
    table.add_column("明细", justify="left", overflow="fold")
    for d in data["dims"]:
        sc = f"{d['score']}" if d["score"] is not None else "[dim]缺失[/dim]"
        table.add_row(d["label"], sc, d["detail"])
    console.print(table)
    if data["highlights"]:
        for x in data["highlights"]:
            console.print(f"[green]★ {x}[/green]")
    if data["risks"]:
        for x in data["risks"]:
            console.print(f"[red]⚠ {x}[/red]")
    if data["timing_notes"]:
        for x in data["timing_notes"]:
            console.print(f"[cyan]择时: {x}[/cyan]")
    print_disclaimer()

    if report:
        html, md = build_doctor_report(data)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"doctor-{code}-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]体检报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "个股体检"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"doctor-{code}-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_holders(code: str, config_path: str | None,
                report: bool = False, push: bool = False) -> None:
    """股东分析：十大股东 + 股东户数趋势。"""
    import os
    from pathlib import Path

    from .holders import (
        analyze_gdhs,
        build_holders_report,
        fetch_gdhs,
        fetch_top10,
    )

    cfg = load_config(config_path)
    if not code:
        console.print("[red]请指定股票代码：holders 002594[/red]")
        return
    market = "hk" if len(code) == 5 and code.isdigit() else "ashare"
    # 找名称
    name = code
    for item in cfg.watchlist:
        if str(item["code"]) == code:
            name = str(item.get("name", code))
            break
    console.print(f"[cyan]正在获取 {name}({code}) 股东数据…[/cyan]")
    holders, report_date = [], ""
    try:
        holders, report_date = fetch_top10(code, market)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]十大股东获取失败：{exc}[/yellow]")
    gdhs_rows = []
    try:
        if market == "ashare":
            gdhs_rows = fetch_gdhs(code)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]股东户数获取失败：{exc}[/yellow]")

    if not holders and not gdhs_rows:
        console.print("[red]未获取到任何股东数据（港股暂不支持）[/red]")
        return

    # 终端输出
    if holders:
        console.print(f"[bold cyan]{name}({code}) 十大股东（报告期 {report_date}）[/bold cyan]")
        table = Table()
        table.add_column("名次", justify="right")
        table.add_column("股东名称", justify="left")
        table.add_column("类型", justify="left")
        table.add_column("持股数", justify="right")
        table.add_column("占比", justify="right")
        table.add_column("变动", justify="left")
        for h in holders:
            style = "green" if h.change in ("减持", "减少") else (
                "red" if h.change in ("增持", "新进") else "")
            chg = h.change + (f" {h.change_ratio:+.1f}%" if h.change_ratio is not None else "")
            chg_cell = f"[{style}]{chg}[/{style}]" if style else chg
            def w(v: float | None) -> str:
                if v is None:
                    return "-"
                return f"{v/1e8:.2f} 亿" if abs(v) >= 1e8 else f"{v/1e4:.0f} 万"
            table.add_row(str(h.rank), h.name, h.share_type,
                          w(h.hold_num), f"{h.ratio:.2f}%" if h.ratio is not None else "-",
                          chg_cell)
        console.print(table)
    if gdhs_rows:
        console.print(f"[bold cyan]股东户数趋势（最新 {gdhs_rows[0].end_date}）[/bold cyan]")
        for line in analyze_gdhs(gdhs_rows):
            console.print(f"  {line}")
    print_disclaimer()

    if push:
        webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
        if webhook:
            from .notify import WebhookNotifier

            lines = [f"股东分析 {name}({code})"]
            lines.extend(analyze_gdhs(gdhs_rows))
            if holders:
                top = ", ".join(f"{h.name} {h.ratio:.1f}%" for h in holders[:3])
                lines.append(f"前三大股东：{top}")
            WebhookNotifier(webhook).send_text("\n".join(lines))
            console.print("[green]已推送 webhook[/green]")

    if report:
        html, md = build_holders_report(
            code, name, market, holders, gdhs_rows, report_date,
        )
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"holders-{code}-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]股东分析报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "股东分析"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"holders-{code}-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_fundflow(code: str | None, config_path: str | None,
                 report: bool = False, push: bool = False) -> None:
    """资金面监控：个股主力资金流 + 沪深港通概要。"""
    import os
    from pathlib import Path

    from .fundflow import (
        build_fundflow_report,
        fetch_fundflow,
        fetch_fundflow_ak,
        fetch_hsgt_summary,
    )

    cfg = load_config(config_path)
    flows = []
    for item in cfg.watchlist:
        market = str(item.get("market", "ashare"))
        if market == "crypto":
            continue
        c = str(item["code"])
        if code and c != code:
            continue
        name = str(item.get("name", c))
        try:
            try:
                flows.append(fetch_fundflow(c, market, name))
            except Exception:  # noqa: BLE001 - push2 不稳时降级
                flows.append(fetch_fundflow_ak(c, name))
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]{name}({c}) 资金流获取失败：{exc}[/yellow]")
    console.print("[cyan]正在获取沪深港通概要…[/cyan]")
    hsgt: list[dict] = []
    try:
        hsgt = fetch_hsgt_summary()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]沪深港通获取失败：{exc}[/yellow]")

    if flows:
        table = Table(title=f"个股主力资金流（{datetime.now():%Y-%m-%d}，亿元）")
        table.add_column("标的", justify="left")
        table.add_column("主力", justify="right")
        table.add_column("超大单", justify="right")
        table.add_column("大单", justify="right")
        table.add_column("中单", justify="right")
        table.add_column("小单", justify="right")
        for f in flows:
            def cell(v: float | None) -> str:
                if v is None:
                    return "-"
                style = "red" if v > 0 else ("green" if v < 0 else "")
                return f"[{style}]{v:+.2f}[/{style}]" if style else f"{v:+.2f}"
            table.add_row(f"{f.name}({f.code})", cell(f.main_net),
                          cell(f.xl_net), cell(f.l_net), cell(f.m_net), cell(f.s_net))
        console.print(table)
    else:
        console.print("[yellow]无资金流数据[/yellow]")

    if hsgt:
        console.print(f"[bold cyan]沪深港通概要（{hsgt[0]['date']}）[/bold cyan]")
        for r in hsgt:
            net = f"{r['net_buy']:+.1f} 亿" if r["net_buy"] is not None else "已停披露"
            console.print(
                f"  {r['board']}({r['direction']}): {net} | "
                f"{r['up']}↑ {r['down']}↓ | {r['index_chg']:+.2f}%"
            )
        console.print("[dim]北向净买入额度自 2024-08 起停止披露[/dim]")
    print_disclaimer()

    if push:
        webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
        if webhook:
            from .notify import WebhookNotifier

            lines = [f"资金面 {datetime.now():%Y-%m-%d}"]
            for f in flows:
                if f.main_net is not None:
                    lines.append(f"{f.name}({f.code}) 主力 {f.main_net:+.2f} 亿")
            for r in hsgt:
                if r["net_buy"] is not None:
                    lines.append(f"{r['board']} {r['net_buy']:+.1f} 亿")
            WebhookNotifier(webhook).send_text("\n".join(lines))
            console.print("[green]已推送 webhook[/green]")

    if report:
        html, md = build_fundflow_report(flows, hsgt)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"fundflow-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]资金面报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "策略验证"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"fundflow-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_events(code: str | None, config_path: str | None, days: int = 30,
               report: bool = False, push: bool = False) -> None:
    """事件日历提醒：扫描自选股未来 N 天解禁/分红除权/业绩预告。"""
    import os
    from pathlib import Path

    from .events import build_events_report, scan_events

    cfg = load_config(config_path)
    codes = [code] if code else None
    console.print(f"[cyan]正在扫描未来 {days} 天事件日历…[/cyan]")
    events = scan_events(cfg, codes=codes, days=days)
    if not events:
        console.print("[yellow]未来无事件[/yellow]")
    else:
        table = Table(title=f"事件日历（未来 {days} 天）")
        table.add_column("日期", justify="left")
        table.add_column("标的", justify="left")
        table.add_column("类型", justify="left")
        table.add_column("事件", justify="left", overflow="fold")
        kind_style = {"解禁": "red", "分红除权": "cyan", "业绩预告": "yellow"}
        for e in events:
            style = kind_style.get(e.kind, "")
            kind = f"[{style}]{e.kind}[/{style}]" if style else e.kind
            table.add_row(e.date, f"{e.name}({e.code})", kind, e.detail)
        console.print(table)
    print_disclaimer()

    if push and events:
        webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
        if webhook:
            from .notify import WebhookNotifier

            lines = [f"事件日历（未来 {days} 天）"]
            for e in events:
                lines.append(f"{e.date} {e.name}({e.code}) {e.kind}：{e.detail}")
            WebhookNotifier(webhook).send_text("\n".join(lines))
            console.print("[green]已推送 webhook[/green]")
        else:
            console.print("[dim]未配置 ASHARE_MONITOR_WEBHOOK，跳过推送[/dim]")

    if report:
        html, md = build_events_report(events, days=days)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"events-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]事件日历报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "事件日历"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"events-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_position(config_path: str | None, report: bool = False,
                 push: bool = False, live: bool = False) -> None:
    """持仓管理与盈亏日报。"""
    import os
    from pathlib import Path

    from .position import (
        build_position_report,
        currency_hint,
        fill_prices,
        load_positions,
    )

    cfg = load_config(config_path)
    positions = load_positions(cfg)
    if not positions:
        console.print("[yellow]未配置持仓：请在 config.local.yaml 的 positions 中填写"
                      "（code/market/cost/shares）[/yellow]")
        return
    positions, as_of = fill_prices(positions, live=live)
    console.print(f"[cyan]持仓盈亏（{'实时' if live else f'收盘 {as_of}'}，"
                  f"{currency_hint(positions)}）[/cyan]")
    table = Table()
    table.add_column("标的", justify="left")
    table.add_column("成本价", justify="right")
    table.add_column("现价", justify="right")
    table.add_column("持仓(股)", justify="right")
    table.add_column("市值", justify="right")
    table.add_column("盈亏额", justify="right")
    table.add_column("盈亏率", justify="right")
    table.add_column("仓位", justify="right")
    for p in positions:
        def cell(v: float | None, sign: bool = False, suffix: str = "") -> str:
            if v is None:
                return "-"
            style = "red" if v > 0 else ("green" if v < 0 else "")
            text = f"{v:+.{2 if not suffix else 1}f}{suffix}" if sign else f"{v:.2f}{suffix}"
            return f"[{style}]{text}[/{style}]" if style else text
        total_mv = sum(x.market_value for x in positions if x.market_value)
        weight = (p.market_value / total_mv * 100) if p.market_value and total_mv else None
        table.add_row(
            f"{p.name}({p.code})", cell(p.cost), cell(p.price),
            f"{p.shares:,.0f}", cell(p.market_value),
            cell(p.pnl, sign=True), cell(p.pnl_pct, sign=True, suffix="%"),
            cell(weight, suffix="%"),
        )
    console.print(table)
    print_disclaimer()

    if push:
        webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
        if webhook:
            from .notify import WebhookNotifier

            lines = [f"持仓盈亏 {as_of or datetime.now().strftime('%Y-%m-%d')}"]
            for p in positions:
                if p.pnl is None:
                    continue
                lines.append(
                    f"{p.name}({p.code}) {p.price:.2f} | "
                    f"盈亏 {p.pnl:+,.0f} ({p.pnl_pct:+.1f}%)"
                )
            WebhookNotifier(webhook).send_text("\n".join(lines))
            console.print("[green]已推送 webhook[/green]")
        else:
            console.print("[dim]未配置 ASHARE_MONITOR_WEBHOOK，跳过推送[/dim]")

    if report:
        html, md = build_position_report(positions, as_of=as_of, live=live)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"position-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]持仓报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "持仓"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"position-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


def run_timing(code: str | None, config_path: str | None,
               report: bool = False, push: bool = False,
               forward: int = 5, concentrated: bool = False) -> None:
    """择时买入提醒：收盘后扫描自选股的技术性买点信号。"""
    import os
    from pathlib import Path

    from .timing import RULES, build_timing_report, scan_watchlist

    cfg = load_config(config_path)
    codes = [code] if code else None
    hint = "（仅筹码集中标的）" if concentrated else ""
    console.print(f"[cyan]正在扫描择时买入信号{hint}（观察 {forward} 交易日）…[/cyan]")
    signals = scan_watchlist(cfg, codes=codes, forward=forward,
                             chip_filter=concentrated)
    if not signals:
        console.print("[yellow]今日未触发任何买入信号（可按 --report 生成空报告）[/yellow]")
    else:
        table = Table(title=f"择时买入信号（{datetime.now():%Y-%m-%d}）")
        table.add_column("标的", justify="left")
        table.add_column("信号", justify="left")
        table.add_column("历史命中率", justify="right")
        table.add_column("平均收益", justify="right")
        table.add_column("样本数", justify="right")
        table.add_column("筹码", justify="left")
        chip_style = {"集中": "red", "分散": "green"}
        for sg in signals:
            style = ("red" if (sg.win_rate or 0) >= 55 else "")
            win = f"{sg.win_rate:.0f}%" if sg.win_rate is not None else "-"
            win_cell = f"[{style}]{win}[/{style}]" if style else win
            avg = f"{sg.avg_return:+.2f}%" if sg.avg_return is not None else "-"
            cst = sg.chip_state or "-"
            c_style = chip_style.get(cst, "")
            chip_cell = f"[{c_style}]{cst}[/{c_style}]" if c_style else cst
            table.add_row(
                f"{sg.name}({sg.code})", f"[bold cyan]{sg.label}[/bold cyan]",
                win_cell, avg, str(sg.signals_count), chip_cell,
            )
        console.print(table)
        for sg in signals:
            extra = f" | 筹码: {sg.chip_desc}" if sg.chip_desc else ""
            console.print(f"[dim]  └─ {sg.message}{extra}[/dim]")
    console.print(f"[dim]规则: {', '.join(v['label'] for v in RULES.values())}[/dim]")
    print_disclaimer()

    # Webhook 推送（有信号才推）
    if push and signals:
        webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
        if webhook:
            from .notify import WebhookNotifier

            lines = [f"择时买入提醒 {datetime.now():%Y-%m-%d}"]
            for sg in signals:
                lines.append(
                    f"{sg.name}({sg.code}) {sg.label} | 历史命中率 "
                    f"{sg.win_rate:.0f}% / 平均 {sg.avg_return:+.2f}%"
                )
            WebhookNotifier(webhook).send_text("\n".join(lines))
            console.print("[green]已推送 webhook[/green]")
        else:
            console.print("[dim]未配置 ASHARE_MONITOR_WEBHOOK，跳过推送[/dim]")

    if report:
        html, md = build_timing_report(signals)
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        out_path = out_dir / f"timing-{today}.html"
        out_path.write_text(html, encoding="utf-8")
        console.print(f"[green]择时信号报告已生成: {out_path}[/green]")
        vault = str(getattr(cfg.obsidian, "vault", "")).strip()
        if vault:
            vdir = Path(vault) / "策略验证"
            vdir.mkdir(parents=True, exist_ok=True)
            md_path = vdir / f"timing-{today}.md"
            md_path.write_text(md, encoding="utf-8")
            console.print(f"[dim]Obsidian: {md_path}[/dim]")


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
    p_pf = sub.add_parser("portfolio", help="组合定投回测（多标的按权重）")
    p_pf.add_argument("codes", help="标的代码，逗号分隔（如 002594,01211）")
    p_pf.add_argument("--weights", default="",
                      help="权重 %，逗号分隔（缺省等权，如 60,40）")
    p_pf.add_argument("--amount", type=float, default=10000.0,
                      help="每月定投总额（默认 10000）")
    p_pf.add_argument("--months", type=int, default=60, help="回看月数（默认 60）")
    p_pf.add_argument("--hold-days", type=int, default=250,
                      help="持有交易日数（默认 250）")
    p_pf.add_argument("--report", action="store_true",
                      help="生成组合回测报告（HTML + Obsidian）")
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
    p_verify = sub.add_parser("verify", help="信号命中率验证（基于回填 K 线回测）")
    p_verify.add_argument("code", help="证券代码，如 002594 / 01211")
    p_verify.add_argument("--market", choices=["ashare", "hk"],
                          help="市场（缺省按代码位数推断）")
    p_verify.add_argument("--rule", help="指定规则（缺省全部），如 up_break")
    p_verify.add_argument("--days", type=int, default=500, help="回看交易日数（默认 500）")
    p_verify.add_argument("--forward", type=int, default=5,
                          help="触发后观察交易日数（默认 5）")
    p_verify.add_argument("--report", action="store_true",
                          help="生成命中率验证报告（HTML + Obsidian）")
    p_timing = sub.add_parser("timing", help="择时买入提醒（收盘后扫描买点信号）")
    p_timing.add_argument("code", nargs="?", default="",
                          help="指定标的代码（缺省扫描全部自选股）")
    p_timing.add_argument("--forward", type=int, default=5,
                          help="历史命中率观察交易日数（默认 5）")
    p_timing.add_argument("--report", action="store_true",
                          help="生成择时信号报告（HTML + Obsidian）")
    p_timing.add_argument("--push", action="store_true",
                          help="有信号时推送 webhook（需 ASHARE_MONITOR_WEBHOOK 环境变量）")
    p_timing.add_argument("--concentrated", action="store_true",
                          help="只保留筹码集中标的的信号（需联网查股东户数，A 股）")
    p_position = sub.add_parser("position", help="持仓管理与盈亏日报")
    p_position.add_argument("--live", action="store_true",
                            help="使用实时行情（缺省用本地收盘价）")
    p_position.add_argument("--report", action="store_true",
                            help="生成持仓报告（HTML + Obsidian）")
    p_position.add_argument("--push", action="store_true",
                            help="推送盈亏日报 webhook")
    p_events = sub.add_parser("events", help="事件日历提醒（解禁/分红除权/业绩预告）")
    p_events.add_argument("code", nargs="?", default="",
                          help="指定标的代码（缺省扫描全部自选股）")
    p_events.add_argument("--days", type=int, default=30,
                          help="未来天数窗口（默认 30）")
    p_events.add_argument("--report", action="store_true",
                          help="生成事件日历报告（HTML + Obsidian）")
    p_events.add_argument("--push", action="store_true",
                          help="推送事件提醒 webhook")
    p_fundflow = sub.add_parser("fundflow", help="资金面监控（个股主力资金流 + 沪深港通）")
    p_fundflow.add_argument("code", nargs="?", default="",
                            help="指定标的代码（缺省扫描全部自选股）")
    p_fundflow.add_argument("--report", action="store_true",
                            help="生成资金面报告（HTML + Obsidian）")
    p_fundflow.add_argument("--push", action="store_true",
                            help="推送资金面概要 webhook")
    p_holders = sub.add_parser("holders", help="股东分析（十大股东 + 股东户数趋势）")
    p_holders.add_argument("code", help="A 股代码，如 002594")
    p_holders.add_argument("--report", action="store_true",
                           help="生成股东分析报告（HTML + Obsidian）")
    p_holders.add_argument("--push", action="store_true",
                           help="推送股东分析摘要 webhook")
    p_doctor = sub.add_parser("doctor", help="个股全方位体检（评分+汇总报告）")
    p_doctor.add_argument("code", help="证券代码，如 002594")
    p_doctor.add_argument("--report", action="store_true",
                          help="生成体检报告（HTML + Obsidian）")
    p_arxiv = sub.add_parser("arxiv", help="arXiv 论文监测（公司署名单位）")
    p_arxiv.add_argument("code", help="证券代码，如 002594（需英文名映射）")
    p_arxiv.add_argument("--name", default="",
                         help="公司英文名（缺省用内置映射，如 BYD）")
    p_arxiv.add_argument("--days", type=int, default=14600,
                         help="回看天数（默认 14600 ≈ 近 40 年，覆盖 arXiv 全历史）")
    p_arxiv.add_argument("--limit", type=int, default=20,
                         help="最多返回论文数（默认 20）")
    p_arxiv.add_argument("--report", action="store_true",
                         help="生成论文监测报告（HTML + Obsidian）")
    p_arxiv.add_argument("--push", action="store_true",
                         help="推送论文摘要 webhook")
    p_hf = sub.add_parser("hf", help="HuggingFace 监测（模型 + 收录论文）")
    p_hf.add_argument("code", help="证券代码，如 00700（腾讯）/ 09988（阿里）")
    p_hf.add_argument("--org", default="",
                      help="HF 组织名（缺省用内置映射，如 Qwen / tencent）")
    p_hf.add_argument("--company", default="",
                      help="论文检索公司名（缺省用内置英文名）")
    p_hf.add_argument("--limit", type=int, default=10,
                      help="最多返回条数（默认 10）")
    p_hf.add_argument("--report", action="store_true",
                      help="生成 HF 监测报告（HTML + Obsidian）")
    p_hf.add_argument("--push", action="store_true",
                      help="推送 HF 摘要 webhook")
    p_lit = sub.add_parser("litigation", help="诉讼监控（自选股重大诉讼披露）")
    p_lit.add_argument("code", nargs="?", default="",
                       help="指定代码（缺省扫描全部自选股）")
    p_lit.add_argument("--days", type=int, default=365,
                       help="回看天数（默认 365）")
    p_lit.add_argument("--report", action="store_true",
                       help="生成诉讼监控报告（HTML + Obsidian）")
    p_lit.add_argument("--push", action="store_true",
                       help="推送诉讼摘要 webhook")
    p_profile = sub.add_parser("profile", help="公司档案（工商信息 + 股权结构）")
    p_profile.add_argument("code", help="证券代码，如 002594")
    p_profile.add_argument("--report", action="store_true",
                           help="生成公司档案报告（HTML + Obsidian）")
    p_gov = sub.add_parser("gov", help="政府侧企业动态（中标/拿地/补助/税收优惠公告）")
    p_gov.add_argument("code", nargs="?", default="",
                       help="指定代码（缺省扫描全部自选股）")
    p_gov.add_argument("--days", type=int, default=30, help="回看天数（默认 30）")
    p_gov.add_argument("--report", action="store_true",
                       help="生成政府动态报告（HTML + Obsidian）")
    p_gov.add_argument("--push", action="store_true",
                       help="推送政府动态摘要 webhook")
    p_site = sub.add_parser("site", help="官方网站链接档案 + 官网公告监控")
    p_site.add_argument("code", nargs="?", default="",
                        help="指定代码（缺省全部自选股）")
    p_site.add_argument("--report", action="store_true",
                        help="生成官网档案报告（HTML + Obsidian）")
    # 公司信号监控（新增 8 个）
    p_insider = sub.add_parser("insider", help="增减持与回购监控（公告信号）")
    p_insider.add_argument("code", nargs="?", default="", help="指定代码")
    p_insider.add_argument("--days", type=int, default=30, help="回看天数")
    p_insider.add_argument("--report", action="store_true", help="生成报告")
    p_insider.add_argument("--push", action="store_true", help="推送 webhook")
    p_pledge = sub.add_parser("pledge", help="股权质押监控（巨潮）")
    p_pledge.add_argument("code", nargs="?", default="", help="指定代码")
    p_pledge.add_argument("--days", type=int, default=7, help="回看天数")
    p_pledge.add_argument("--report", action="store_true", help="生成报告")
    p_pledge.add_argument("--push", action="store_true", help="推送 webhook")
    p_rating = sub.add_parser("rating", help="券商研报监控（含 EPS 预测）")
    p_rating.add_argument("code", nargs="?", default="", help="指定代码")
    p_rating.add_argument("--days", type=int, default=30, help="回看天数")
    p_rating.add_argument("--report", action="store_true", help="生成报告")
    p_rating.add_argument("--push", action="store_true", help="推送 webhook")
    p_lhb = sub.add_parser("lhb", help="龙虎榜监控（自选股上榜）")
    p_lhb.add_argument("code", nargs="?", default="", help="指定代码")
    p_lhb.add_argument("--days", type=int, default=10, help="回看天数")
    p_lhb.add_argument("--report", action="store_true", help="生成报告")
    p_lhb.add_argument("--push", action="store_true", help="推送 webhook")
    p_north = sub.add_parser("north", help="北向持股监控（个股持股明细）")
    p_north.add_argument("code", nargs="?", default="", help="指定代码")
    p_north.add_argument("--report", action="store_true", help="生成报告")
    p_north.add_argument("--push", action="store_true", help="推送 webhook")
    p_block = sub.add_parser("block", help="大宗交易监控（折溢率）")
    p_block.add_argument("code", nargs="?", default="", help="指定代码")
    p_block.add_argument("--days", type=int, default=10, help="回看天数")
    p_block.add_argument("--report", action="store_true", help="生成报告")
    p_block.add_argument("--push", action="store_true", help="推送 webhook")
    p_valuation = sub.add_parser("valuation", help="估值分位（PE/PB 历史百分位）")
    p_valuation.add_argument("code", nargs="?", default="", help="指定代码")
    p_valuation.add_argument("--years", type=int, default=5, help="回看年数")
    p_valuation.add_argument("--report", action="store_true", help="生成报告")
    p_valuation.add_argument("--push", action="store_true", help="推送 webhook")
    p_sector = sub.add_parser("sector", help="月度产销快报（行业景气先行指标）")
    p_sector.add_argument("code", nargs="?", default="", help="指定代码")
    p_sector.add_argument("--report", action="store_true", help="生成报告")
    p_sector.add_argument("--push", action="store_true", help="推送 webhook")

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
    elif args.command == "portfolio":
        run_portfolio(args.codes, args.weights or None, args.amount,
                      args.months, args.hold_days, args.config,
                      report=args.report)
    elif args.command == "review":
        run_review(args.date, args.config,
                   backfill_start=args.backfill, backfill_end=args.end)
    elif args.command == "scan":
        run_scan(args.config)
    elif args.command == "report":
        period = "yearly" if args.yearly else ("monthly" if args.monthly else "weekly")
        run_report(period, args.date, args.config)
    elif args.command == "verify":
        run_verify(args.code, args.market, args.rule, args.days,
                   args.forward, args.config, report=args.report)
    elif args.command == "timing":
        run_timing(args.code or None, args.config,
                   report=args.report, push=args.push, forward=args.forward,
                   concentrated=args.concentrated)
    elif args.command == "position":
        run_position(args.config, report=args.report,
                     push=args.push, live=args.live)
    elif args.command == "events":
        run_events(args.code or None, args.config, days=args.days,
                   report=args.report, push=args.push)
    elif args.command == "fundflow":
        run_fundflow(args.code or None, args.config,
                     report=args.report, push=args.push)
    elif args.command == "holders":
        run_holders(args.code, args.config,
                    report=args.report, push=args.push)
    elif args.command == "doctor":
        run_doctor(args.code, args.config, report=args.report)
    elif args.command == "arxiv":
        run_arxiv(args.code, args.config, args.name or None,
                  days=args.days, limit=args.limit,
                  report=args.report, push=args.push)
    elif args.command == "hf":
        run_hf(args.code, args.config, args.org or None,
               args.company or None, limit=args.limit,
               report=args.report, push=args.push)
    elif args.command == "litigation":
        run_litigation(args.code or None, args.config, days=args.days,
                       report=args.report, push=args.push)
    elif args.command == "profile":
        run_profile(args.code, args.config, report=args.report)
    elif args.command == "gov":
        run_gov(args.code or None, args.config, days=args.days,
                report=args.report, push=args.push)
    elif args.command == "site":
        run_site(args.code or None, args.config, report=args.report)
    elif args.command == "insider":
        run_insider(args.code or None, args.config, days=args.days,
                    report=args.report, push=args.push)
    elif args.command == "pledge":
        run_pledge(args.code or None, args.config, days=args.days,
                   report=args.report, push=args.push)
    elif args.command == "rating":
        run_rating(args.code or None, args.config, days=args.days,
                   report=args.report, push=args.push)
    elif args.command == "lhb":
        run_lhb(args.code or None, args.config, days=args.days,
                report=args.report, push=args.push)
    elif args.command == "north":
        run_north(args.code or None, args.config,
                  report=args.report, push=args.push)
    elif args.command == "block":
        run_block(args.code or None, args.config, days=args.days,
                  report=args.report, push=args.push)
    elif args.command == "valuation":
        run_valuation(args.code or None, args.config, years=args.years,
                      report=args.report, push=args.push)
    elif args.command == "sector":
        run_sector(args.code or None, args.config,
                   report=args.report, push=args.push)
    else:
        run_monitor(args.config)


if __name__ == "__main__":
    main()
