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


def _pct_html(value: float) -> str:
    cls = "up" if value > 0 else ("down" if value < 0 else "")
    return f'<span class="{cls}">{value:+.2f}%</span>'


def _quote_rows(quotes: list[Quote]) -> str:
    rows = []
    for q in quotes:
        amp = q.amplitude
        rows.append(
            "<tr>"
            f"<td>{q.code}</td><td>{q.name}</td>"
            f"<td>{q.price:.2f}</td>"
            f"<td>{_pct_html(q.change_pct)}</td>"
            f"<td>{f'{amp:.2f}%' if amp is not None else '-'}</td>"
            f"<td>{q.volume:,.0f}</td>"
            f"<td>{q.turnover / 1e8:.2f}亿</td>"
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
            f"<td>{q.turnover / 1e8:,.0f}亿</td>"
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
) -> str:
    """拼装复盘报告 HTML。charts: [{id, title, dates, kdata, volumes}]。"""
    chart_cards = []
    chart_inits = []
    for c in (index_charts or []) + charts:
        chart_cards.append(f'<div class="card"><div class="chart" id="{c["id"]}"></div></div>')
        chart_inits.append(
            f'renderKline("{c["id"]}", {json.dumps(c["title"], ensure_ascii=False)}, '
            f'{json.dumps(c["dates"])}, {json.dumps(c["kdata"])}, {json.dumps(c["volumes"])});'
        )

    index_section = ""
    if index_quotes:
        index_section = f"""
<h2>一、大盘指数</h2>
<div class="card">
<table>
<tr><th>代码</th><th>指数</th><th>点位</th><th>涨跌幅</th><th>振幅</th><th>成交额</th></tr>
{_index_rows(index_quotes)}
</table>
</div>"""

    stock_sec_no = "二" if index_quotes else "一"
    alert_sec_no = "三" if index_quotes else "二"
    kline_sec_no = "四" if index_quotes else "三"

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
{index_section}
<h2>{stock_sec_no}、自选股当日表现</h2>
<div class="card">
<table>
<tr><th>代码</th><th>名称</th><th>收盘/最新</th><th>涨跌幅</th><th>振幅</th><th>成交量(手)</th><th>成交额</th></tr>
{_quote_rows(quotes)}
</table>
</div>

<h2>{alert_sec_no}、当日预警时间线（共 {len(records)} 条）</h2>
<div class="card">
<table>
<tr><th>时间</th><th>标的</th><th>规则</th><th style="text-align:left">详情</th></tr>
{_alert_rows(records)}
</table>
</div>

<h2>{kline_sec_no}、近期 K 线走势</h2>
{''.join(chart_cards)}

<div class="footer">{_DISCLAIMER}</div>
</div>
<script>{_JS}
{chr(10).join(chart_inits)}
</script>
</body>
</html>"""


# ---------- 报告生成 ----------

def _fetch_kline_chart(symbol: str, days: int, adjust: str,
                       title_prefix: str = "", market: str = "ashare") -> dict | None:
    """拉取单个标的的 K 线图数据，失败返回 None。"""
    try:
        df, name = fetch_history(symbol, days=days, adjust=adjust, market=market)
    except Exception as exc:  # noqa: BLE001
        logger.warning("复盘：%s(%s) K 线拉取失败: %s", symbol, market, exc)
        return None
    code6 = symbol[-6:]
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

    # 自选股 K 线（图题带波动画像）
    cache = ProfileCache(days=cfg.monitor.profile_days)
    charts: list[dict] = []
    for market, mcodes in watch_groups.items():
        for code in mcodes:
            chart = _fetch_kline_chart(
                code, kline_days,
                adjust="qfq" if market != "crypto" else "",
                market=market,
            )
            if chart:
                profile = cache.get(code, market)
                if profile:
                    chart["title"] += f"  |  {profile}"
                charts.append(chart)

    html = build_html(
        date_str, quotes, records, charts,
        index_quotes=index_quotes, index_charts=index_charts,
    )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"review-{date_str}.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info("复盘报告已生成: %s", out_path)
    return out_path, quotes, records


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

_PERIOD_DAYS = {"weekly": 7, "monthly": 30}
_PERIOD_LABEL = {"weekly": "周报", "monthly": "月报"}


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
    return out_path


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
