"""收盘复盘报告：预警持久化 + HTML 报告生成。

工作流程：
1. 监控运行期间，触发的预警以 JSONL 追加到 logs/alerts/alerts-YYYY-MM-DD.jsonl
2. 收盘后（或手动 review 命令）汇总：当日行情、预警时间线、
   各股 K 线与波动画像，生成 output/review-YYYY-MM-DD.html
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from .alerts import Alert
from .analysis import ProfileCache, fetch_history
from .config import Config
from .quotes import Quote, fetch_spot_quotes

logger = logging.getLogger(__name__)

ALERTS_DIR = "logs/alerts"
OUTPUT_DIR = "output"


# ---------- 预警持久化 ----------

def alerts_file(date_str: str, directory: str = ALERTS_DIR) -> Path:
    return Path(directory) / f"alerts-{date_str}.jsonl"


def append_alerts(alerts: list[Alert], date_str: str | None = None,
                  directory: str = ALERTS_DIR) -> Path:
    """把当天触发的预警追加写入 JSONL 文件。"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    path = alerts_file(date_str, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for a in alerts:
            f.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")
    return path


def load_alerts(date_str: str, directory: str = ALERTS_DIR) -> list[dict]:
    """读取某天的预警记录，不存在返回空列表。"""
    path = alerts_file(date_str, directory)
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------- 规则中文名 ----------

RULE_NAMES = {
    "change_pct": "涨跌幅",
    "price_above": "价格上破",
    "price_below": "价格下破",
    "weibi": "委比失衡",
    "big_order": "大单挂单",
    "amplitude": "振幅波动",
}


# ---------- HTML 模板 ----------

_CSS = """
body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f5f6f8;
       color: #1f2329; margin: 0; padding: 24px; }
.container { max-width: 1080px; margin: 0 auto; }
h1 { font-size: 22px; } h2 { font-size: 17px; margin-top: 32px;
     border-left: 4px solid #c0392b; padding-left: 8px; }
.meta { color: #86909c; font-size: 13px; }
.card { background: #fff; border-radius: 8px; padding: 16px 20px;
        margin-top: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
th { color: #86909c; font-weight: normal; }
.up { color: #c0392b; font-weight: 600; } .down { color: #1e9e4f; font-weight: 600; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px;
       background: #fdf0ef; color: #c0392b; font-size: 12px; }
.profile { color: #4e5969; font-size: 12px; margin: 4px 0 0; }
.chart { width: 100%; height: 360px; }
.footer { margin-top: 32px; color: #86909c; font-size: 12px; line-height: 1.8; }
"""

_JS = """
function renderKline(elId, title, dates, kdata, volumes) {
  var chart = echarts.init(document.getElementById(elId));
  var upColor = '#c0392b', downColor = '#1e9e4f';
  chart.setOption({
    title: { text: title, left: 8, textStyle: { fontSize: 14 } },
    animation: false,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 60, right: 16, top: 40, height: '58%' },
      { left: 60, right: 16, top: '74%', height: '16%' }
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { fontSize: 10 } }
    ],
    yAxis: [
      { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#f0f0f0' } } },
      { scale: true, gridIndex: 1, splitLine: { show: false } }
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
    series: [
      { type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0, data: kdata,
        itemStyle: { color: upColor, color0: downColor,
                     borderColor: upColor, borderColor0: downColor } },
      { type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes,
        itemStyle: { color: '#c9cdd4' } }
    ]
  });
}
"""

_DISCLAIMER = (
    "本报告基于公开行情数据自动生成，仅供学习与技术研究，不构成任何投资建议。"
    "市场有风险，投资需谨慎。过往表现不预示未来收益。"
)


def _cn_num(n: int) -> str:
    """阿拉伯数字转中文序号（1-10）。"""
    return ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"][n]


def _pct_html(value: float) -> str:
    cls = "up" if value > 0 else ("down" if value < 0 else "")
    return f'<span class="{cls}">{value:+.2f}%</span>'


def _is_hk_code(code: str) -> bool:
    """按代码判断是否港股（5 位纯数字）。用于币种/单位标注。"""
    return len(code) == 5 and code.isdigit()


def _quote_rows(quotes: list[Quote]) -> str:
    rows = []
    for q in quotes:
        amp = q.amplitude
        hk = _is_hk_code(q.code)
        volume_unit = "股" if hk else "手"
        turnover = "-" if q.turnover is None else (
            f"{q.turnover / 1e8:.2f}亿港元" if hk else f"{q.turnover / 1e8:.2f}亿"
        )
        rows.append(
            "<tr>"
            f"<td>{q.code}</td><td>{q.name}</td>"
            f"<td>{q.price:.2f}</td>"
            f"<td>{_pct_html(q.change_pct)}</td>"
            f"<td>{f'{amp:.2f}%' if amp is not None else '-'}</td>"
            f"<td>{q.volume:,.0f}{volume_unit}</td>"
            f"<td>{turnover}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _alert_rows(records: list[dict]) -> str:
    if not records:
        return '<tr><td colspan="4" style="text-align:center;color:#86909c">当日无预警记录</td></tr>'
    rows = []
    for r in records:
        rule = RULE_NAMES.get(r["rule"], r["rule"])
        profile_html = (
            f'<div class="profile">波动画像：{r["profile"]}</div>'
            if r.get("profile") else ""
        )
        rows.append(
            "<tr>"
            f"<td>{r['time']}</td>"
            f"<td>{r['name']}({r['code']})</td>"
            f'<td><span class="tag">{rule}</span></td>'
            f"<td style=\"text-align:left\">{r['message']}{profile_html}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _index_rows(quotes: list[Quote]) -> str:
    rows = []
    for q in quotes:
        amp = q.amplitude
        rows.append(
            "<tr>"
            f"<td>{q.code}</td><td>{q.name}</td>"
            f"<td>{q.price:,.2f}</td>"
            f"<td>{_pct_html(q.change_pct)}</td>"
            f"<td>{f'{amp:.2f}%' if amp is not None else '-'}</td>"
            f"<td>{f'{q.turnover / 1e8:,.0f}亿' if q.turnover is not None else '-'}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def build_html(
    date_str: str,
    quotes: list[Quote],
    records: list[dict],
    charts: list[dict],
    index_quotes: list[Quote] | None = None,
    index_charts: list[dict] | None = None,
    indicator_rows: list[dict] | None = None,
    news_rows: list[dict] | None = None,
    financial_rows: list[dict] | None = None,
    ipo_rows: list[dict] | None = None,
    timing_signals: list[dict] | None = None,
    ip_rows: list[dict] | None = None,
) -> str:
    """拼装复盘报告 HTML。charts: [{id, title, dates, kdata, volumes}]。

    章节按存在顺序编号（大盘指数 → 技术指标 → 当日表现 → 预警 → 财报 → 公告研报 → IPO → 择时信号 → K线）。
    """
    chart_cards = []
    chart_inits = []
    for c in (index_charts or []) + charts:
        chart_cards.append(f'<div class="card"><div class="chart" id="{c["id"]}"></div></div>')
        chart_inits.append(
            f'renderKline("{c["id"]}", {json.dumps(c["title"], ensure_ascii=False)}, '
            f'{json.dumps(c["dates"])}, {json.dumps(c["kdata"])}, {json.dumps(c["volumes"])});'
        )

    sections: list[str] = []

    def add_section(title: str, body: str) -> None:
        sections.append(f"<h2>{_cn_num(len(sections) + 1)}、{title}</h2>{body}")

    if index_quotes:
        add_section("大盘指数", f"""
<div class="card">
<table>
<tr><th>代码</th><th>指数</th><th>点位</th><th>涨跌幅</th><th>振幅</th><th>成交额</th></tr>
{_index_rows(index_quotes)}
</table>
</div>""")

    if indicator_rows:
        rows = []
        for r in indicator_rows:
            macd_style = "red" if r["macd"].startswith("金叉") else (
                "green" if r["macd"].startswith("死叉") else ""
            )
            rows.append(
                "<tr>"
                f"<td>{r['market']}</td><td>{r['name']}({r['code']})</td>"
                f'<td><span class="{macd_style}">{r["macd"]}</span></td>'
                f"<td>{r['rsi']}</td><td>{r['kdj']}</td><td>{r['boll']}</td>"
                "</tr>"
            )
        add_section("技术指标状态", f"""
<div class="card">
<table>
<tr><th>市场</th><th>标的</th><th>MACD</th><th>RSI(14)</th><th>KDJ</th><th>BOLL</th></tr>
{''.join(rows)}
</table>
</div>""")

    add_section("自选股当日表现", f"""
<div class="card">
<table>
<tr><th>代码</th><th>名称</th><th>收盘/最新</th><th>涨跌幅</th><th>振幅</th><th>成交量</th><th>成交额</th></tr>
{_quote_rows(quotes)}
</table>
</div>""")

    add_section(f"当日预警时间线（共 {len(records)} 条）", f"""
<div class="card">
<table>
<tr><th>时间</th><th>标的</th><th>规则</th><th style="text-align:left">详情</th></tr>
{_alert_rows(records)}
</table>
</div>""")

    if financial_rows:
        rows = []
        for r in financial_rows:
            def _f(v, nd=1):
                return f"{v:.{nd}f}" if v is not None else "-"
            rev = _pct_html(r["revenue_yoy"]) if r["revenue_yoy"] is not None else "-"
            prof = _pct_html(r["profit_yoy"]) if r["profit_yoy"] is not None else "-"
            currency = "（港元）" if _is_hk_code(str(r["code"])) else ""
            rows.append(
                "<tr>"
                f"<td>{r['name']}({r['code']}){currency}</td>"
                f"<td>{r['report_date']}</td>"
                f"<td>{_f(r['revenue'])}</td><td>{rev}</td>"
                f"<td>{_f(r['net_profit'])}</td><td>{prof}</td>"
                f"<td>{_f(r['roe'])}%</td><td>{_f(r['gross_margin'])}%</td>"
                f"<td>{_f(r['net_margin'])}%</td>"
                "</tr>"
            )
        add_section("财报速览（最新报告期）", f"""
<div class="card">
<table>
<tr><th>标的</th><th>报告期</th><th>营收(亿)</th><th>营收同比</th><th>净利(亿)</th><th>净利同比</th><th>ROE</th><th>毛利率</th><th>净利率</th></tr>
{''.join(rows)}
</table>
</div>""")

    if news_rows:
        from .announcements import is_major

        # 重大事项置顶（其余按日期倒序）
        ordered = sorted(
            news_rows,
            key=lambda r: (not (r["kind"] == "ann" and is_major(r["title"])), r["date"]),
        )
        rows = []
        for r in ordered:
            kind = "公告" if r["kind"] == "ann" else "研报"
            src = r.get("org") or ""
            major = r["kind"] == "ann" and is_major(r["title"])
            kind_tag = (
                f'<span class="tag" style="background:#fde8e8;color:#e02e24">'
                f'★重大·{kind}</span>'
                if major else f'<span class="tag">{kind}</span>'
            )
            title_html = (
                f'<span style="color:#e02e24;font-weight:600">{r["title"]}</span>'
                if major else r["title"]
            )
            rows.append(
                "<tr>"
                f"<td>{r['date']}</td><td>{r['name']}({r['code']})</td>"
                f"<td>{kind_tag}</td>"
                f"<td style=\"text-align:left\">{title_html}"
                f"{f'<div class=\"profile\">{src}</div>' if src else ''}</td>"
                f'<td><a href="{r["url"]}">原文</a></td>'
                "</tr>"
            )
        add_section("公告与研报", f"""
<div class="card">
<table>
<tr><th>日期</th><th>标的</th><th>类型</th><th style="text-align:left">标题</th><th>原文</th></tr>
{''.join(rows)}
</table>
</div>""")

    if ip_rows:
        rows = []
        for r in ip_rows:
            status_style = "green" if r["np"] else "#86909c"
            rows.append(
                "<tr>"
                f"<td>{r['name']}</td><td>{r['np']}</td><td>{r['na']}</td>"
                f'<td><span class="tag" style="color:{status_style}">{r["status"]}</span></td>'
                f"<td>{r['ipc']}</td><td>{r['latest']}</td>"
                f"<td>{r['updated']}</td>"
                "</tr>"
            )
        add_section("知识产权布局（智慧芽）", f"""
<div class="card">
<table>
<tr><th>标的</th><th>专利(采样)</th><th>论文</th><th>法律状态</th><th>技术聚焦</th><th>最新专利</th><th>回填时间</th></tr>
{''.join(rows)}
</table>
<div style="margin-top:8px;font-size:12px;color:#86909c">专利/论文为智慧芽会话内采样快照（每标的 ≤15 件专利），非全量；未回填标的显示 0。数据仅供研发布局参考。</div>
</div>""")

    if ipo_rows:
        rows = []
        for r in ipo_rows:
            stage_style = {"待申购": "#2980b9", "待定价": "#b7950b",
                           "待上市": "#8e44ad", "已上市": "#27ae60"}.get(r["stage"], "")
            stage_cell = (
                f'<span class="tag" style="color:{stage_style}">{r["stage"]}</span>'
                if stage_style else r["stage"]
            )
            price = f"{r['issue_price']:.2f}" if r["issue_price"] is not None else "-"
            ipe = f"{r['industry_pe']:.1f}" if r["industry_pe"] is not None else "-"
            funds = f"{r['raise_funds']:.2f}" if r["raise_funds"] is not None else "-"
            rows.append(
                "<tr>"
                f"<td>{r['code']}</td><td>{r['name']}</td>"
                f"<td>{r['market']}</td><td>{r['apply_date'] or '-'}</td>"
                f"<td>{price}</td><td>{ipe}</td><td>{funds}</td>"
                f"<td>{stage_cell}</td>"
                "</tr>"
            )
        add_section("近期 IPO", f"""
<div class="card">
<table>
<tr><th>代码</th><th>名称</th><th>交易所</th><th>申购日</th><th>发行价</th><th>行业PE</th><th>募资(亿)</th><th>状态</th></tr>
{''.join(rows)}
</table>
</div>""")

    if timing_signals:
        rows = []
        for sg in timing_signals:
            win = f"{sg['win_rate']:.0f}%" if sg["win_rate"] is not None else "-"
            avg = f"{sg['avg_return']:+.2f}%" if sg["avg_return"] is not None else "-"
            style = "red" if (sg["win_rate"] or 0) >= 55 else ""
            win_cell = f'<span class="{style}">{win}</span>' if style else win
            rows.append(
                "<tr>"
                f"<td>{sg['name']}({sg['code']})</td>"
                f'<td><span class="tag" style="background:#e8f3ff;color:#1677ff">{sg["label"]}</span></td>'
                f'<td style="text-align:left">{sg["message"]}</td>'
                f"<td>{win_cell}</td><td>{avg}</td><td>{sg['signals_count']}</td>"
                "</tr>"
            )
        add_section("择时买入信号", f"""
<div class="card">
<table>
<tr><th>标的</th><th>信号</th><th style="text-align:left">说明</th><th>历史命中率</th><th>平均收益</th><th>样本数</th></tr>
{''.join(rows)}
</table>
<div style="margin-top:8px;font-size:12px;color:#86909c">历史命中率 = 该信号在标的上近 5 年全部历史信号触发后 5 个交易日收益为正的比例。信号为统计提示，不构成投资建议。</div>
</div>""")

    add_section("近期 K 线走势", "".join(chart_cards))

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>A 股复盘报告 {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
<h1>A 股收盘复盘报告</h1>
<div class="meta">{date_str} · 生成于 {datetime.now():%Y-%m-%d %H:%M:%S} · 数据来源：新浪/腾讯/东方财富公开行情接口</div>
{chr(10).join(sections)}

<div class="footer">{_DISCLAIMER}</div>
</div>
<script>{_JS}
{chr(10).join(chart_inits)}
</script>
</body>
</html>"""


# ---------- 报告生成 ----------

def _financial_row(code: str, name: str, r: dict) -> dict:
    """从财报记录构造速览行（本地库 load_financials 格式）。"""
    return {
        "code": code, "name": name,
        "report_date": r.get("report_date", ""),
        "revenue": round(r["revenue"], 1) if r.get("revenue") is not None else None,
        "net_profit": round(r["net_profit"], 1) if r.get("net_profit") is not None else None,
        "revenue_yoy": round(r["revenue_yoy"], 1) if r.get("revenue_yoy") is not None else None,
        "profit_yoy": round(r["profit_yoy"], 1) if r.get("profit_yoy") is not None else None,
        "roe": round(r["roe"], 1) if r.get("roe") is not None else None,
        "gross_margin": round(r["gross_margin"], 1) if r.get("gross_margin") is not None else None,
        "net_margin": round(r["net_margin"], 1) if r.get("net_margin") is not None else None,
    }


def _fetch_kline_chart(symbol: str, days: int, adjust: str,
                       title_prefix: str = "", market: str = "ashare") -> dict | None:
    """拉取单个标的的 K 线图数据，失败返回 None。

    返回 dict 额外包含 indicator 字段：当日指标状态行（供报告标注）。
    """
    try:
        df, name = fetch_history(symbol, days=days, adjust=adjust, market=market)
    except Exception as exc:  # noqa: BLE001
        logger.warning("复盘：%s(%s) K 线拉取失败: %s", symbol, market, exc)
        return None
    code6 = symbol[-6:]
    indicator = None
    try:
        from .indicators import compute_indicators

        ir = compute_indicators(df)
        indicator = {
            "code": code6,
            "name": name or code6,
            "market": market,
            "summary": ir.summary_line(),
            "macd": ir.macd.trend + (
                f"({ir.macd.days_since_cross}日前)" if ir.macd.days_since_cross is not None else ""
            ),
            "rsi": f"{ir.rsi.value:.0f}",
            "kdj": ir.kdj.trend,
            "boll": ir.boll.position,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("复盘：%s 指标计算失败: %s", symbol, exc)
    return {
        "id": f"chart-{code6}-{'idx' if title_prefix else 'stk'}",
        "title": f"{title_prefix}{name or code6}({code6})  近{days}日",
        "dates": [str(d)[:10] for d in df["日期"]],
        "kdata": [
            [round(float(o), 2), round(float(c), 2),
             round(float(lo), 2), round(float(hi), 2)]
            for o, c, lo, hi in zip(df["开盘"], df["收盘"], df["最低"], df["最高"])
        ],
        "volumes": [int(v) for v in df["成交量"]],
        "indicator": indicator,
    }


def generate_review(
    date_str: str | None,
    cfg: Config,
    alerts_dir: str = ALERTS_DIR,
    output_dir: str = OUTPUT_DIR,
) -> Path:
    """生成某天的复盘报告 HTML，返回文件路径。

    各数据项独立容错：行情 / 指数 / K 线拉取失败不阻塞其余部分。
    """
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    kline_days = cfg.review.kline_days

    # 大盘指数（行情 + K 线）
    index_quotes: list[Quote] = []
    index_charts: list[dict] = []
    if cfg.review.indexes:
        try:
            index_quotes, _ = fetch_spot_quotes(
                cfg.review.indexes, sources=cfg.quotes.sources
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("复盘：指数行情拉取失败: %s", exc)
        for symbol in cfg.review.indexes:
            chart = _fetch_kline_chart(symbol, kline_days, adjust="")
            if chart:
                index_charts.append(chart)

    # 自选股行情（按市场分组拉取）
    quotes: list[Quote] = []
    watch_groups: dict[str, list[str]] = {}
    for item in cfg.watchlist:
        watch_groups.setdefault(str(item.get("market", "ashare")), []).append(
            str(item["code"])
        )
    for market, mcodes in watch_groups.items():
        try:
            qs, _source = fetch_spot_quotes(
                mcodes,
                sources=cfg.quotes.sources if market == "ashare" else None,
                market=market,
            )
            quotes.extend(qs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("复盘：%s 行情快照拉取失败: %s", market, exc)

    records = load_alerts(date_str, alerts_dir)

    # 自选股 K 线（图题带波动画像与指标摘要）
    cache = ProfileCache(days=cfg.monitor.profile_days)
    charts: list[dict] = []
    indicator_rows: list[dict] = []
    for market, mcodes in watch_groups.items():
        for code in mcodes:
            chart = _fetch_kline_chart(
                code, kline_days,
                adjust="qfq" if market != "crypto" else "",
                market=market,
            )
            if chart:
                profile = cache.get(code, market)
                extra = []
                if profile:
                    extra.append(profile)
                if chart.get("indicator"):
                    extra.append(chart["indicator"]["summary"])
                    indicator_rows.append(chart["indicator"])
                if extra:
                    chart["title"] += "  |  " + "  |  ".join(extra)
                charts.append(chart)

    # 财报速览（A 股 + 港股；读库优先取最新报告期，库空回退联网，失败不阻塞）
    financial_rows: list[dict] = []
    for item in cfg.watchlist:
        market = str(item.get("market", "ashare"))
        if market not in ("ashare", "hk"):
            continue
        code = str(item["code"])
        name = str(item.get("name", code))
        try:
            from .storage import load_financials

            rows = load_financials(code)
            if rows:  # 库内有历史财报（backfill --financial 回填）
                financial_rows.append(_financial_row(code, name, rows[0]))
                continue
            from .fundamentals import fetch_financials

            periods = fetch_financials(code, periods=1, market=market)
            if periods:
                p = periods[0]
                financial_rows.append({
                    "code": code, "name": name,
                    "report_date": p.report_date,
                    "revenue": round(p.revenue, 1) if p.revenue is not None else None,
                    "net_profit": round(p.net_profit, 1) if p.net_profit is not None else None,
                    "revenue_yoy": round(p.revenue_yoy, 1) if p.revenue_yoy is not None else None,
                    "profit_yoy": round(p.profit_yoy, 1) if p.profit_yoy is not None else None,
                    "roe": round(p.roe, 1) if p.roe is not None else None,
                    "gross_margin": round(p.gross_margin, 1) if p.gross_margin is not None else None,
                    "net_margin": round(p.net_margin, 1) if p.net_margin is not None else None,
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("复盘：%s 财报拉取失败: %s", code, exc)

    # 近期 IPO（未来 30 天申购/上市 + 最近 7 天已上市，失败不阻塞）
    ipo_rows: list[dict] = []
    try:
        from .ipo import fetch_ipo_list

        for rec in fetch_ipo_list(limit=30):
            stage = rec.stage()
            if stage in ("待申购", "待上市"):
                ipo_rows.append({
                    "code": rec.code, "name": rec.name,
                    "market": rec.market.replace("证券交易所", ""),
                    "apply_date": rec.apply_date,
                    "issue_price": rec.issue_price,
                    "industry_pe": rec.industry_pe,
                    "raise_funds": rec.raise_funds,
                    "stage": stage,
                })
    except Exception as exc:  # noqa: BLE001
        logger.warning("复盘：近期 IPO 拉取失败: %s", exc)

    # 公告与研报（仅 A 股；失败不阻塞报告生成）
    news_rows: list[dict] = []
    for item in cfg.watchlist:
        if str(item.get("market", "ashare")) != "ashare":
            continue
        code = str(item["code"])
        name = str(item.get("name", code))
        try:
            from .announcements import fetch_announcements, fetch_research_reports
            from .storage import record_announcements, record_research_reports

            anns = fetch_announcements(code, limit=3)
            reps = fetch_research_reports(code, days=30, limit=2)
            # 拉取结果同步入库（url 去重，失败不阻塞报告）
            try:
                record_announcements(anns, code, name=name)
                record_research_reports(reps, code, name=name)
            except Exception as exc2:  # noqa: BLE001
                logger.warning("复盘：%s 公告/研报入库失败: %s", code, exc2)
            for a in anns:
                news_rows.append({
                    "kind": "ann", "code": code, "name": name,
                    "date": a["date"], "title": a["title"], "url": a["url"],
                })
            for r in reps:
                news_rows.append({
                    "kind": "report", "code": code, "name": name,
                    "date": r["date"], "title": r["title"],
                    "url": r["url"], "org": r["org"],
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("复盘：%s 公告/研报拉取失败: %s", code, exc)
    news_rows.sort(key=lambda r: r["date"], reverse=True)

    # 择时买入信号（读本地 K 线扫描，失败不阻塞；当日复盘用实时行情不适用历史扫描时跳过）
    timing_signals: list[dict] = []
    try:
        from .timing import scan_watchlist

        timing_signals = [
            sg.to_dict() for sg in scan_watchlist(cfg)
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("复盘：择时信号扫描失败: %s", exc)

    # 知识产权布局（智慧芽回填，失败不阻塞）
    ip_rows: list[dict] = []
    try:
        from collections import Counter

        from .import_data import get_all_ip_assets

        assets = get_all_ip_assets()
        for item in cfg.watchlist:
            nm = str(item.get("name", ""))
            ip = None
            for k, v in assets.items():
                if nm and (nm in k or k in nm):
                    ip = v
                    break
            pats = (ip or {}).get("patents") or []
            papers = (ip or {}).get("papers") or []
            row = {"name": nm, "np": len(pats), "na": len(papers),
                   "status": "未回填" if not pats else "-",
                   "ipc": "-", "latest": "-",
                   "updated": (ip or {}).get("updated", "")}
            if pats:
                st = Counter(p.get("legal_status") or "unknown" for p in pats)
                act, pend = st.get("active", 0), st.get("pending", 0)
                ipc_cnt = Counter((p.get("ipc") or "")[:4]
                                  for p in pats if p.get("ipc"))
                row["ipc"] = (ipc_cnt.most_common(1)[0][0]
                              if ipc_cnt else "-")
                row["status"] = f"有效{act}/申请{pend}"
                latest = max(pats, key=lambda x: str(x.get("date") or ""))
                row["latest"] = f"{str(latest.get('date', ''))[:10]}"
            ip_rows.append(row)
    except Exception as exc:  # noqa: BLE001
        logger.warning("复盘：知识产权布局读取失败: %s", exc)

    html = build_html(
        date_str, quotes, records, charts,
        index_quotes=index_quotes, index_charts=index_charts,
        indicator_rows=indicator_rows, news_rows=news_rows,
        financial_rows=financial_rows, ipo_rows=ipo_rows,
        timing_signals=timing_signals, ip_rows=ip_rows,
    )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"review-{date_str}.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info("复盘报告已生成: %s", out_path)

    # 导出 Markdown 到 Obsidian 库（配置了 vault 才执行）
    obsidian_path = export_obsidian(
        cfg, date_str, quotes, records, index_quotes,
        indicator_rows, news_rows, financial_rows, ipo_rows,
        html_path=out_path,
    )
    if obsidian_path:
        logger.info("Obsidian Markdown 已导出: %s", obsidian_path)

    return out_path, quotes, records


def export_obsidian(
    cfg: Config,
    date_str: str,
    quotes: list[Quote],
    records: list[dict],
    index_quotes: list[Quote],
    indicator_rows: list[dict],
    news_rows: list[dict],
    financial_rows: list[dict],
    ipo_rows: list[dict],
    html_path: Path,
) -> Path | None:
    """把复盘报告导出为 Markdown 存入 Obsidian vault（未配置则返回 None）。"""
    vault = getattr(cfg.obsidian, "vault", "").strip()
    if not vault:
        return None
    md = build_review_markdown(
        date_str, quotes, records, index_quotes,
        indicator_rows, news_rows, financial_rows, ipo_rows,
        html_path=html_path,
    )
    vault_dir = Path(vault)
    reports_dir = vault_dir / (getattr(cfg.obsidian, "reports_dir", "A股复盘") or "A股复盘")
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / f"review-{date_str}.md"
    out.write_text(md, encoding="utf-8")
    return out


# ---------- 历史复盘回填 ----------

def _quote_from_kline(market: str, code: str, name: str,
                      row: dict, prev_close: float) -> Quote:
    """用历史 K 线单根构造当日行情（回填历史复盘用，离线）。"""
    close = float(row["close"])
    prev = float(prev_close) if prev_close else close
    change = close - prev
    change_pct = change / prev * 100 if prev else 0.0
    return Quote(
        code=code, name=name, price=close, change_pct=round(change_pct, 2),
        change=round(change, 4), volume=float(row["volume"]), turnover=None,
        high=float(row["high"]), low=float(row["low"]),
        open=float(row["open"]), prev_close=prev,
        timestamp=datetime.strptime(row["date"], "%Y-%m-%d"),
    )


def _chart_from_local_rows(code: str, name: str, market: str,
                           rows: list[dict], kline_days: int,
                           end_idx: int) -> dict:
    """从本地 K 线构造图表数据（回填历史复盘用，离线；含指标状态）。"""
    start = max(0, end_idx - kline_days + 1)
    window = rows[start:end_idx + 1]
    indicator = None
    try:
        import pandas as pd

        from .indicators import compute_indicators

        df = pd.DataFrame({
            "日期": [r["date"] for r in window],
            "开盘": [r["open"] for r in window],
            "收盘": [r["close"] for r in window],
            "最高": [r["high"] for r in window],
            "最低": [r["low"] for r in window],
            "成交量": [r["volume"] for r in window],
        })
        ir = compute_indicators(df)
        indicator = {
            "code": code, "name": name, "market": market,
            "summary": ir.summary_line(),
            "macd": ir.macd.trend + (
                f"({ir.macd.days_since_cross}日前)"
                if ir.macd.days_since_cross is not None else ""
            ),
            "rsi": f"{ir.rsi.value:.0f}",
            "kdj": ir.kdj.trend,
            "boll": ir.boll.position,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("回填复盘：%s 指标计算失败: %s", code, exc)
    return {
        "id": f"chart-{code[-6:]}-stk",
        "title": f"{name or code}({code[-6:]})  近{kline_days}日",
        "dates": [r["date"] for r in window],
        "kdata": [
            [round(float(r["open"]), 2), round(float(r["close"]), 2),
             round(float(r["low"]), 2), round(float(r["high"]), 2)]
            for r in window
        ],
        "volumes": [int(float(r["volume"])) for r in window],
        "indicator": indicator,
    }


def backfill_reviews(
    start_date: str,
    end_date: str,
    cfg: Config,
    output_dir: str = OUTPUT_DIR,
    alerts_dir: str = ALERTS_DIR,
    db_path: str | Path | None = None,
) -> list[Path]:
    """回填历史复盘报告：用本地 klines 表为区间内每个交易日生成 HTML + Obsidian MD。

    历史日期无法获得实时行情快照、指数行情与 IPO 日历，这些板块自动省略；
    行情表格 / K 线图 / 技术指标全部来自本地回填数据（需先 backfill --kline）。
    财报速览联网拉取一次（最新报告期，失败则省略）；公告研报从本地库按日期过滤。

    :return: 生成的 HTML 文件路径列表
    """
    from .storage import DB_PATH as DEFAULT_DB
    from .storage import (
        load_announcements,
        load_financials,
        load_klines,
        load_research_reports,
    )

    db_path = db_path or DEFAULT_DB

    # 1. 收集自选标的的本地 K 线
    watch_items: list[dict] = []
    for item in cfg.watchlist:
        market = str(item.get("market", "ashare"))
        code = str(item["code"])
        name = str(item.get("name", code))
        if market == "crypto":
            logger.warning("回填复盘：crypto 暂不支持，跳过 %s", code)
            continue
        rows = load_klines(code, market, db_path=db_path)
        if len(rows) < 2:
            logger.warning(
                "回填复盘：%s(%s) 本地 K 线不足（%d 根），跳过；请先 backfill --kline",
                code, market, len(rows),
            )
            continue
        watch_items.append({"market": market, "code": code, "name": name, "rows": rows})
    if not watch_items:
        raise RuntimeError("没有可回填的标的（本地 K 线不足），请先运行 backfill --kline")

    # 2. 交易日并集，取区间
    all_days = sorted({r["date"] for w in watch_items for r in w["rows"]})
    start_idx = next((i for i, d in enumerate(all_days) if d >= start_date), len(all_days))
    end_idx = next((i for i, d in enumerate(all_days) if d > end_date), len(all_days))
    days = all_days[start_idx:end_idx]
    if not days:
        raise RuntimeError(
            f"区间 {start_date} ~ {end_date} 内无交易日（本地 K 线范围 "
            f"{all_days[0]} ~ {all_days[-1]}）"
        )

    # 3. 财报：读本地库全量（backfill --financial 回填），逐日取"报告期≤当日"最近一期；
    #    库空时回退联网拉最新一期（共享兜底，失败不阻塞）
    fin_cache: dict[str, dict] = {}  # code -> {"name":.., "rows":[..]}
    fallback_financial: list[dict] = []
    for item in cfg.watchlist:
        market = str(item.get("market", "ashare"))
        if market not in ("ashare", "hk"):
            continue
        code, name = str(item["code"]), str(item.get("name", item["code"]))
        try:
            rows = load_financials(code, db_path=db_path)
            if rows:
                fin_cache[code] = {"name": name, "rows": rows}  # 已按报告期倒序
                continue
            from .fundamentals import fetch_financials

            periods = fetch_financials(code, periods=1, market=market)
            if periods:
                p = periods[0]
                fallback_financial.append({
                    "code": code, "name": name,
                    "report_date": p.report_date,
                    "revenue": round(p.revenue, 1) if p.revenue is not None else None,
                    "net_profit": round(p.net_profit, 1) if p.net_profit is not None else None,
                    "revenue_yoy": round(p.revenue_yoy, 1) if p.revenue_yoy is not None else None,
                    "profit_yoy": round(p.profit_yoy, 1) if p.profit_yoy is not None else None,
                    "roe": round(p.roe, 1) if p.roe is not None else None,
                    "gross_margin": round(p.gross_margin, 1) if p.gross_margin is not None else None,
                    "net_margin": round(p.net_margin, 1) if p.net_margin is not None else None,
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("回填复盘：%s 财报读取失败: %s", code, exc)

    def _financials_for(day: str) -> list[dict]:
        """当日财报速览：报告期 ≤ 该交易日的最近一期（库优先）+ 兜底。"""
        rows_out = []
        for code, entry in fin_cache.items():
            latest = next(
                (r for r in entry["rows"] if r["report_date"] <= day), None
            )
            if latest:
                rows_out.append(_financial_row(code, entry["name"], latest))
        return rows_out or fallback_financial

    # 4. 公告研报本地缓存（按日期过滤；仅 A 股）
    news_cache: list[dict] = []
    for w in watch_items:
        if w["market"] != "ashare":
            continue
        for a in load_announcements(w["code"], limit=1000, db_path=db_path):
            news_cache.append({
                "kind": "ann", "code": w["code"], "name": w["name"],
                "date": a["date"], "title": a["title"], "url": a["url"],
            })
        for r in load_research_reports(w["code"], limit=1000, db_path=db_path):
            news_cache.append({
                "kind": "report", "code": w["code"], "name": w["name"],
                "date": r["date"], "title": r["title"],
                "url": r["url"], "org": r["org"],
            })

    # 5. 逐交易日生成
    kline_days = cfg.review.kline_days
    prepared = [
        {**w, "date_idx": {r["date"]: i for i, r in enumerate(w["rows"])}}
        for w in watch_items
    ]
    out_files: list[Path] = []
    total = len(days)
    for i, day in enumerate(days, 1):
        quotes: list[Quote] = []
        charts: list[dict] = []
        indicator_rows: list[dict] = []
        for w in prepared:
            di = w["date_idx"].get(day)
            if di is None:
                continue
            rows = w["rows"]
            prev = rows[di - 1]["close"] if di > 0 else rows[di]["close"]
            quotes.append(_quote_from_kline(
                w["market"], w["code"], w["name"], rows[di], prev,
            ))
            chart = _chart_from_local_rows(
                w["code"], w["name"], w["market"], rows, kline_days, di,
            )
            if chart.get("indicator"):
                indicator_rows.append(chart["indicator"])
            charts.append(chart)

        news_rows = [it for it in news_cache if it["date"] <= day]
        news_rows.sort(key=lambda r: r["date"], reverse=True)
        news_rows = news_rows[:20]

        records = load_alerts(day, alerts_dir)

        html = build_html(
            day, quotes, records, charts,
            indicator_rows=indicator_rows, news_rows=news_rows,
            financial_rows=_financials_for(day),
        )
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"review-{day}.html"
        out_path.write_text(html, encoding="utf-8")
        day_financial = _financials_for(day)
        export_obsidian(
            cfg, day, quotes, records, [], indicator_rows,
            news_rows, day_financial, [], html_path=out_path,
        )
        out_files.append(out_path)
        logger.info("回填复盘 [%d/%d] %s: %s", i, total, day, out_path)

    return out_files


def build_review_markdown(
    date_str: str,
    quotes: list[Quote],
    records: list[dict],
    index_quotes: list[Quote] | None = None,
    indicator_rows: list[dict] | None = None,
    news_rows: list[dict] | None = None,
    financial_rows: list[dict] | None = None,
    ipo_rows: list[dict] | None = None,
    html_path: Path | None = None,
) -> str:
    """把复盘数据渲染为 Obsidian Markdown（纯函数，便于测试）。

    板块与 HTML 报告保持一致；K 线图（ECharts）无法入 Markdown，
    通过链接指向 HTML 报告。
    """
    lines = [
        "---",
        f"title: A股复盘 {date_str}",
        f"date: {date_str}",
        "tags: [复盘, A股]",
        f"generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "---",
        "",
        f"# A股收盘复盘 {date_str}",
        "",
    ]

    def _md_table(headers: list[str], rows: list[list[str]]) -> str:
        sep = "| " + " | ".join(["---"] * len(headers)) + " |"
        out = ["| " + " | ".join(headers) + " |", sep]
        out += ["| " + " | ".join(r) + " |" for r in rows]
        return "\n".join(out)

    def _fmt(v, suffix: str = "", nd: int = 2) -> str:
        return f"{v:.{nd}f}{suffix}" if v is not None else "-"

    # 大盘指数
    if index_quotes:
        lines.append("## 大盘指数")
        lines.append("")
        lines.append(_md_table(
            ["指数", "点位", "涨跌幅", "振幅", "成交额"],
            [[q.name, _fmt(q.price, nd=2), f"{q.change_pct:+.2f}%",
              _fmt(q.amplitude, "%", 1),
              _fmt(q.turnover / 1e8, "亿", 1) if q.turnover is not None else "-"]
             for q in index_quotes],
        ))
        lines.append("")

    # 技术指标
    if indicator_rows:
        lines.append("## 技术指标状态")
        lines.append("")
        lines.append(_md_table(
            ["市场", "标的", "MACD", "RSI(14)", "KDJ", "BOLL"],
            [[r["market"], f"{r['name']}({r['code']})", r["macd"], r["rsi"],
              r["kdj"], r["boll"]] for r in indicator_rows],
        ))
        lines.append("")

    # 自选股当日表现
    lines.append("## 自选股当日表现")
    lines.append("")
    lines.append(_md_table(
        ["代码", "名称", "收盘/最新", "涨跌幅", "振幅", "成交额"],
        [[q.code, q.name, _fmt(q.price), f"{q.change_pct:+.2f}%",
          _fmt(q.amplitude, "%", 1),
          _fmt(q.turnover / 1e8, "亿", 1) if q.turnover is not None else "-"]
         for q in quotes],
    ))
    lines.append("")

    # 预警时间线
    lines.append(f"## 当日预警时间线（共 {len(records)} 条）")
    lines.append("")
    if records:
        for r in records:
            lines.append(f"- {r.get('time', '')} **{r.get('name', r.get('code', ''))}** "
                         f"`{r.get('rule', '')}` — {r.get('message', '')}")
    else:
        lines.append("当日无预警")
    lines.append("")

    # 财报速览
    if financial_rows:
        lines.append("## 财报速览（最新报告期）")
        lines.append("")
        lines.append(_md_table(
            ["标的", "报告期", "营收(亿)", "营收同比", "净利(亿)", "净利同比", "ROE", "毛利率"],
            [[f"{r['name']}({r['code']})"
              + ("（港元）" if _is_hk_code(str(r["code"])) else ""),
              r["report_date"],
              _fmt(r["revenue"]), f"{r['revenue_yoy']:+.1f}%" if r["revenue_yoy"] is not None else "-",
              _fmt(r["net_profit"]), f"{r['profit_yoy']:+.1f}%" if r["profit_yoy"] is not None else "-",
              _fmt(r["roe"], "%", 1), _fmt(r["gross_margin"], "%", 1)]
             for r in financial_rows],
        ))
        lines.append("")

    # 公告与研报
    if news_rows:
        from .announcements import is_major

        lines.append("## 公告与研报（★=重大事项）")
        lines.append("")
        ordered = sorted(
            news_rows,
            key=lambda r: (not (r["kind"] == "ann" and is_major(r["title"])), r["date"]),
        )
        for r in ordered:
            kind = "公告" if r["kind"] == "ann" else "研报"
            extra = f"（{r['org']}）" if r.get("org") else ""
            major = r["kind"] == "ann" and is_major(r["title"])
            mark = "★" if major else ""
            lines.append(f"- [{mark}{kind}] {r['date']} **{r['title']}**{extra} — {r['url']}")
        lines.append("")

    # 近期 IPO
    if ipo_rows:
        lines.append("## 近期 IPO")
        lines.append("")
        lines.append(_md_table(
            ["代码", "名称", "交易所", "申购日", "发行价", "行业PE", "募资(亿)", "状态"],
            [[r["code"], r["name"], r["market"], r["apply_date"] or "-",
              _fmt(r["issue_price"]), _fmt(r["industry_pe"], nd=1),
              _fmt(r["raise_funds"]), r["stage"]] for r in ipo_rows],
        ))
        lines.append("")

    # K 线走势（引用 HTML 报告）
    lines.append("## 近期 K 线走势")
    lines.append("")
    lines.append("K 线图（ECharts 蜡烛图）请查看 HTML 报告："
                 + (f"[review-{date_str}.html]({html_path})" if html_path else f"`output/review-{date_str}.html`"))
    lines.append("")
    lines.append(f"> {_DISCLAIMER}")
    return "\n".join(lines)


def build_push_summary(
    date_str: str, quotes: list[Quote], records: list[dict], report_path: Path
) -> str:
    """生成 webhook 推送的复盘摘要文本。"""
    lines = [f"A 股复盘 {date_str}"]
    for q in quotes:
        lines.append(f"{q.name}({q.code}) {q.price:.2f} {q.change_pct:+.2f}%")
    lines.append(f"当日预警 {len(records)} 条")
    lines.append(f"报告：{report_path}")
    return "\n".join(lines)


# ---------- 周 / 月复盘汇总 ----------

_PERIOD_DAYS = {"weekly": 7, "monthly": 30, "yearly": 365}
_PERIOD_LABEL = {"weekly": "周报", "monthly": "月报", "yearly": "年报"}


def _period_range(period: str, end_date: str | None) -> tuple[str, str]:
    """返回周期起止日期。"""
    end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
    start = end - timedelta(days=_PERIOD_DAYS.get(period, 7) - 1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def generate_period_report(
    period: str, end_date: str | None, cfg: Config, output_dir: str = OUTPUT_DIR
) -> Path:
    """基于 SQLite 积累的数据生成周 / 月复盘汇总报告。"""
    from .storage import (
        count_alerts_by_code,
        count_alerts_by_rule,
        count_alerts_daily,
        load_alerts_range,
        load_reviews_range,
    )

    start, end = _period_range(period, end_date)
    label = _PERIOD_LABEL.get(period, "汇总")

    rule_counts = count_alerts_by_rule(start, end)
    daily_counts = count_alerts_daily(start, end)
    code_counts = count_alerts_by_code(start, end)
    alerts = load_alerts_range(start, end)
    reviews = load_reviews_range(start, end)

    # 区间行情表现（每只自选标的：期初→期末涨跌幅）
    stock_rows = []
    for item in cfg.watchlist:
        code = str(item["code"])
        market = str(item.get("market", "ashare"))
        try:
            df, name = fetch_history(
                code, days=_PERIOD_DAYS.get(period, 7) * 2 + 10,
                adjust="qfq" if market != "crypto" else "",
                market=market,
            )
            df = df[df["日期"].astype(str) >= start]
            if len(df) >= 2:
                first, last = float(df["收盘"].iloc[0]), float(df["收盘"].iloc[-1])
                stock_rows.append({
                    "code": code, "name": name or code, "market": market,
                    "first": first, "last": last,
                    "return_pct": (last / first - 1) * 100,
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("汇总：%s 行情拉取失败: %s", code, exc)

    html = _build_period_html(
        label, start, end, alerts, rule_counts, daily_counts,
        code_counts, stock_rows, reviews,
    )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"report-{period}-{end}.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info("%s汇总报告已生成: %s", label, out_path)

    # 导出 Markdown 到 Obsidian 独立库（配置了 vault 才执行）
    obsidian_out = export_period_obsidian(
        cfg, period, label, start, end,
        alerts, rule_counts, daily_counts, code_counts, stock_rows, reviews,
        html_path=out_path,
    )
    if obsidian_out:
        logger.info("Obsidian %s Markdown 已导出: %s", label, obsidian_out)

    return out_path


def export_period_obsidian(
    cfg: Config,
    period: str,
    label: str,
    start: str,
    end: str,
    alerts: list[dict],
    rule_counts: list[dict],
    daily_counts: list[dict],
    code_counts: list[dict],
    stock_rows: list[dict],
    reviews: list[dict],
    html_path: Path,
) -> Path | None:
    """把周/月/年报导出为 Markdown 存入 Obsidian vault（未配置则返回 None）。"""
    vault = getattr(cfg.obsidian, "vault", "").strip()
    if not vault:
        return None
    md = build_period_markdown(
        period, label, start, end, alerts, rule_counts, daily_counts,
        code_counts, stock_rows, reviews, html_path=html_path,
    )
    out_dir = Path(vault) / "汇总报告"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"report-{period}-{end}.md"
    out.write_text(md, encoding="utf-8")
    return out


def build_period_markdown(
    period: str,
    label: str,
    start: str,
    end: str,
    alerts: list[dict],
    rule_counts: list[dict],
    daily_counts: list[dict],
    code_counts: list[dict],
    stock_rows: list[dict],
    reviews: list[dict],
    html_path: Path | None = None,
) -> str:
    """把周期汇总数据渲染为 Obsidian Markdown（纯函数，便于测试）。"""
    lines = [
        "---",
        f"title: A股{label}复盘汇总 {end}",
        f"date: {end}",
        f"tags: [复盘, A股, {label}]",
        f"period: {start} ~ {end}",
        f"generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "---",
        "",
        f"# A股{label}复盘汇总",
        "",
        f"**区间：{start} ~ {end}** · 预警 {len(alerts)} 条 · 复盘 {len(reviews)} 篇",
        "",
    ]

    def _md_table(headers: list[str], rows: list[list[str]]) -> str:
        sep = "| " + " | ".join(["---"] * len(headers)) + " |"
        out = ["| " + " | ".join(headers) + " |", sep]
        out += ["| " + " | ".join(r) + " |" for r in rows]
        return "\n".join(out)

    # 区间行情表现
    if stock_rows:
        lines.append("## 区间行情表现")
        lines.append("")
        lines.append(_md_table(
            ["市场", "标的", "期初", "期末", "区间涨跌"],
            [[r["market"], f"{r['name']}({r['code']})", f"{r['first']:.2f}",
              f"{r['last']:.2f}", f"{r['return_pct']:+.2f}%"]
             for r in sorted(stock_rows, key=lambda x: x["return_pct"], reverse=True)],
        ))
        lines.append("")

    # 预警统计
    lines.append("## 预警统计")
    lines.append("")
    lines.append(_md_table(
        ["规则", "次数"],
        [[RULE_NAMES.get(r["rule"], r["rule"]), str(r["count"])] for r in rule_counts],
    ))
    lines.append("")
    if daily_counts:
        lines.append("### 每日预警数")
        lines.append("")
        lines.append(_md_table(
            ["日期", "预警数"],
            [[r["date"], str(r["count"])] for r in daily_counts],
        ))
        lines.append("")
    if code_counts:
        lines.append("### 预警排行（按标的）")
        lines.append("")
        lines.append(_md_table(
            ["标的", "预警数"],
            [[f"{r['name'] or r['code']}({r['code']})", str(r["count"])] for r in code_counts],
        ))
        lines.append("")

    # 每日复盘记录
    lines.append("## 每日复盘记录")
    lines.append("")
    if reviews:
        for r in reviews:
            lines.append(f"- {r['date']}：预警 {r['alert_count']} 条 · {r['generated_at']}")
    else:
        lines.append("区间内暂无复盘记录")
    lines.append("")

    # 预警明细
    lines.append(f"## 预警明细（共 {len(alerts)} 条）")
    lines.append("")
    if alerts:
        for r in alerts:
            lines.append(
                f"- {r['date']} {r['time']} **{r['name'] or r['code']}({r['code']})** "
                f"`{RULE_NAMES.get(r['rule'], r['rule'])}` — {r['message']}"
            )
    else:
        lines.append("区间内无预警")
    lines.append("")

    lines.append("## 图表")
    lines.append("")
    lines.append("预警统计图表（ECharts）请查看 HTML 报告："
                 + (f"[report-{period}-{end}.html]({html_path})" if html_path
                    else f"`output/report-{period}-{end}.html`"))
    lines.append("")
    lines.append(f"> {_DISCLAIMER}")
    return "\n".join(lines)


_PERIOD_JS = """
function renderBar(elId, title, cats, values, color) {
  var chart = echarts.init(document.getElementById(elId));
  chart.setOption({
    title: { text: title, left: 8, textStyle: { fontSize: 13 } },
    tooltip: {},
    grid: { left: 50, right: 20, top: 42, bottom: 40 },
    xAxis: { type: 'category', data: cats, axisLabel: { rotate: 40, fontSize: 10 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f0f0' } } },
    series: [{
      type: 'bar', data: values,
      itemStyle: { color: color, borderRadius: [3, 3, 0, 0] },
      label: { show: true, position: 'top', fontSize: 10 }
    }]
  });
}
"""


def _build_period_html(
    label: str, start: str, end: str,
    alerts: list[dict],
    rule_counts: list[dict],
    daily_counts: list[dict],
    code_counts: list[dict],
    stock_rows: list[dict],
    reviews: list[dict],
) -> str:
    def bar_block(el_id: str, title: str, cats: list[str], vals: list, color: str) -> str:
        return (
            f'<div class="card"><div class="chart-sm" id="{el_id}"></div></div>'
            f'<script>renderBar("{el_id}", {json.dumps(title, ensure_ascii=False)}, '
            f'{json.dumps(cats, ensure_ascii=False)}, {json.dumps(vals)}, "{color}");</script>'
        )

    # 行情表现表
    stock_table = ""
    if stock_rows:
        rows = []
        for r in sorted(stock_rows, key=lambda x: x["return_pct"], reverse=True):
            cls = "up" if r["return_pct"] > 0 else ("down" if r["return_pct"] < 0 else "")
            rows.append(
                "<tr>"
                f"<td>{r['market']}</td><td>{r['name']}({r['code']})</td>"
                f"<td>{r['first']:.2f}</td><td>{r['last']:.2f}</td>"
                f'<td><span class="{cls}">{r["return_pct"]:+.2f}%</span></td>'
                "</tr>"
            )
        stock_table = f"""
<h2>一、区间行情表现（{start} ~ {end}）</h2>
<div class="card">
<table>
<tr><th>市场</th><th>标的</th><th>期初</th><th>期末</th><th>区间涨跌</th></tr>
{''.join(rows)}
</table>
</div>"""

    # 每日复盘记录
    review_rows = ""
    if reviews:
        rows = []
        for r in reviews:
            rows.append(
                "<tr>"
                f"<td>{r['date']}</td><td>预警 {r['alert_count']} 条</td>"
                f"<td>{r['generated_at']}</td>"
                f'<td><a href="{r["report_path"]}">{r["report_path"]}</a></td>'
                "</tr>"
            )
        review_rows = "".join(rows)

    rule_cats = [RULE_NAMES.get(r["rule"], r["rule"]) for r in rule_counts]
    rule_vals = [r["count"] for r in rule_counts]
    daily_cats = [r["date"][5:] for r in daily_counts]
    daily_vals = [r["count"] for r in daily_counts]
    code_cats = [f"{r['name'] or r['code']}" for r in code_counts]
    code_vals = [r["count"] for r in code_counts]

    # 每日预警明细表
    alert_detail = ""
    if alerts:
        rows = []
        for r in alerts:
            rows.append(
                "<tr>"
                f"<td>{r['date']}</td><td>{r['time']}</td>"
                f"<td>{r['name']}({r['code']})</td>"
                f'<td><span class="tag">{RULE_NAMES.get(r["rule"], r["rule"])}</span></td>'
                f"<td style=\"text-align:left\">{r['message']}</td>"
                "</tr>"
            )
        alert_detail = f"""
<h2>四、预警明细（{start} ~ {end}，共 {len(alerts)} 条）</h2>
<div class="card">
<table>
<tr><th>日期</th><th>时间</th><th>标的</th><th>规则</th><th style="text-align:left">详情</th></tr>
{''.join(rows)}
</table>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>A 股{label}复盘汇总 {end}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>{_CSS}
.chart-sm {{ width: 100%; height: 260px; }}
</style>
</head>
<body>
<div class="container">
<h1>A 股{label}复盘汇总</h1>
<div class="meta">{start} ~ {end} · 生成于 {datetime.now():%Y-%m-%d %H:%M:%S} · 数据来源：公开行情接口 + 本地监控积累</div>
{stock_table}

<h2>二、预警统计</h2>
<div class="card" style="display:flex;gap:12px;flex-wrap:wrap">
<div style="flex:1;min-width:220px">
<p class="meta">区间共触发 <b>{len(alerts)}</b> 条预警</p>
<p class="meta">涉及 <b>{len(code_counts)}</b> 只标的</p>
<p class="meta">累计生成 <b>{len(reviews)}</b> 份日复盘</p>
</div>
</div>
{bar_block("chart-rule", "预警规则分布", rule_cats or ["-"], rule_vals or [0], "#c0392b")}
{bar_block("chart-daily", "每日预警数", daily_cats or ["-"], daily_vals or [0], "#2980b9")}
{bar_block("chart-code", "预警排行（按标的）", code_cats or ["-"], code_vals or [0], "#8e44ad")}

<h2>三、每日复盘记录</h2>
<div class="card">
<table>
<tr><th>日期</th><th>摘要</th><th>生成时间</th><th>报告</th></tr>
{review_rows or '<tr><td colspan="4" style="text-align:center;color:#86909c">区间内暂无复盘记录</td></tr>'}
</table>
</div>
{alert_detail}

<div class="footer">{_DISCLAIMER}</div>
</div>
<script>{_JS}{_PERIOD_JS}</script>
</body>
</html>"""
