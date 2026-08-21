"""股东分析：指定股票代码的十大股东与股东户数趋势。

数据源（直连，akshare 兜底）：
- 十大股东：东方财富 F10（emweb.securities.eastmoney.com PageSDGD，按报告期）
- 股东户数：东财数据中心 RPT_HOLDERNUM_DET（历史序列，2013 年起）

解读规则（如实呈现，不夸大）：
- 户数较半年前减少 >10% → 筹码集中（常见的潜在看涨信号）
- 户数较半年前增加 >10% → 筹码分散（潜在承压信号）
- 前十大股东合计占比、机构/个人结构

声明：股东分析为公开信息统计，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_HEADERS_F10 = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://emweb.securities.eastmoney.com/",
}
_HEADERS_DC = {
    "User-Agent": _HEADERS_F10["User-Agent"],
    "Referer": "https://data.eastmoney.com/",
}
_DC_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"


@dataclass
class TopHolder:
    rank: int
    name: str
    share_type: str
    hold_num: float        # 持股数（股）
    ratio: float | None    # 占总股本 %
    change: str            # 增减（不变/新进/减持/增持...）
    change_ratio: float | None  # 变动比率 %

    def to_dict(self) -> dict:
        return {
            "rank": self.rank, "name": self.name, "share_type": self.share_type,
            "hold_num": self.hold_num, "ratio": self.ratio,
            "change": self.change, "change_ratio": self.change_ratio,
        }


@dataclass
class HolderNumRow:
    end_date: str
    holder_num: float       # 本次户数
    prev_num: float | None  # 上次户数
    change_pct: float | None  # 户数增减比例 %
    avg_market_cap: float | None  # 户均持股市值（元）
    avg_hold_num: float | None    # 户均持股数量
    total_market_cap: float | None

    def to_dict(self) -> dict:
        return {
            "end_date": self.end_date, "holder_num": self.holder_num,
            "prev_num": self.prev_num, "change_pct": self.change_pct,
            "avg_market_cap": self.avg_market_cap, "avg_hold_num": self.avg_hold_num,
        }


def _prefix(code: str) -> str:
    return ("SH" if code.startswith("6") else "SZ") + code


def _latest_report_date(code: str, market: str) -> str:
    """确定最近报告期：优先本地财报库，否则取最近季度末。"""
    try:
        from .storage import load_financials

        rows = load_financials(code)
        if rows:
            return rows[0]["report_date"]
    except Exception:  # noqa: BLE001
        pass
    # 回退：最近已披露季度的报告期（按披露规律取最近季度末）
    now = datetime.now()
    quarters = [(f"{y}-03-31", f"{y}-06-30", f"{y}-09-30", f"{y}-12-31")
                for y in (now.year, now.year - 1)]
    # 披露规律：一季报 4-30 前、半年报 8-31 前、三季报 10-31 前、年报次年 4-30 前
    for q in [q for y in quarters for q in y]:
        d = datetime.strptime(q, "%Y-%m-%d")
        # 报告期 q 已披露（q + 披露缓冲 4 个月）
        if d + timedelta(days=122) <= now:
            return q
    return quarters[0][0]


def fetch_top10(code: str, market: str = "ashare",
                report_date: str | None = None) -> tuple[list[TopHolder], str]:
    """查询十大股东（返回 股东列表, 报告期）。港股无接口返回空。"""
    if market == "hk":
        return [], ""
    rd = report_date or _latest_report_date(code, market)
    resp = requests.get(
        "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageSDGD",
        params={"code": _prefix(code), "date": rd},
        headers=_HEADERS_F10, timeout=12,
    )
    resp.raise_for_status()
    data = (resp.json().get("sdgd") or [])
    holders = []
    for x in data:
        change = x.get("HOLDER_CHANGE") or "不变"
        holders.append(TopHolder(
            rank=int(x.get("HOLDER_RANK") or 0),
            name=str(x.get("HOLDER_NAME") or ""),
            share_type=str(x.get("SHARES_TYPE") or ""),
            hold_num=float(x.get("HOLD_NUM") or 0),
            ratio=_f(x.get("HOLD_NUM_RATIO")),
            change=change,
            change_ratio=_f(x.get("HOLDER_CHANGE_RATIO")),
        ))
    return holders, str(data[0].get("END_DATE", rd))[:10] if data else rd


def fetch_gdhs(code: str) -> list[HolderNumRow]:
    """股东户数历史（END_DATE 降序，最新在前）。"""
    resp = requests.get(
        _DC_API,
        params={
            "reportName": "RPT_HOLDERNUM_DET",
            "columns": "ALL",
            "pageSize": 100, "pageNumber": 1,
            "filter": f'(SECURITY_CODE="{code[-6:]}")',
            "sortColumns": "END_DATE", "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        },
        headers=_HEADERS_DC, timeout=12,
    )
    resp.raise_for_status()
    rows = []
    for x in (resp.json().get("result") or {}).get("data") or []:
        rows.append(HolderNumRow(
            end_date=str(x.get("END_DATE") or "")[:10],
            holder_num=_f(x.get("HOLDER_NUM")) or 0.0,
            prev_num=_f(x.get("PRE_HOLDER_NUM")),
            change_pct=_f(x.get("INTERVAL_CHRATE")),
            avg_market_cap=_f(x.get("AVG_MARKET_CAP")),
            avg_hold_num=_f(x.get("AVG_HOLD_NUM")),
            total_market_cap=_f(x.get("TOTAL_MARKET_CAP")),
        ))
    return rows


def _f(v) -> float | None:
    try:
        if v is None or v == "" or v == "--" or v == "NaN":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def analyze_gdhs(rows: list[HolderNumRow]) -> list[str]:
    """股东户数趋势解读（如实统计）。"""
    lines = []
    if len(rows) < 2:
        return lines
    latest = rows[0]
    lines.append(
        f"最新 {latest.end_date} 股东户数 {latest.holder_num:,.0f} 户"
        + (f"（环比 {latest.change_pct:+.1f}%）" if latest.change_pct is not None else "")
    )
    # 半年 / 一年前对比
    six_m = (datetime.strptime(latest.end_date, "%Y-%m-%d") - timedelta(days=180)).strftime("%Y-%m-%d")
    year_a = (datetime.strptime(latest.end_date, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    for label, anchor in (("半年", six_m), ("一年", year_a)):
        base = next((r for r in rows if r.end_date <= anchor), None)
        if base and base.holder_num:
            chg = (latest.holder_num / base.holder_num - 1) * 100
            lines.append(f"较{label}前（{base.end_date}）户数 {chg:+.1f}%")
    # 结论
    if len(rows) >= 4:
        chg_6m = None
        base = next((r for r in rows if r.end_date <= six_m), None)
        if base and base.holder_num:
            chg_6m = (latest.holder_num / base.holder_num - 1) * 100
        if chg_6m is not None:
            if chg_6m <= -10:
                lines.append(f"户数半年减少 {abs(chg_6m):.0f}%（筹码集中，潜在看涨信号之一）")
            elif chg_6m >= 10:
                lines.append(f"户数半年增加 {chg_6m:.0f}%（筹码分散，潜在承压信号）")
            else:
                lines.append("户数半年变化不大（筹码稳定）")
    return lines


def _fmt_wan(v: float | None) -> str:
    """数值转万/亿可读格式。"""
    if v is None:
        return "-"
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f} 亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.0f} 万"
    return f"{v:.0f}"


def build_holders_report(
    code: str, name: str, market: str,
    holders: list[TopHolder], gdhs_rows: list[HolderNumRow],
    report_date: str, as_of: str | None = None,
) -> tuple[str, str]:
    """生成股东分析报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    insights = analyze_gdhs(gdhs_rows)

    top_ratio = sum(h.ratio for h in holders if h.ratio is not None)
    tr = []
    md_rows = [
        "| 名次 | 股东名称 | 股份类型 | 持股数 | 占比 | 变动 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for h in holders:
        style = ""
        if h.change in ("减持", "减少"):
            style = "down"
        elif h.change in ("增持", "新进"):
            style = "up"
        chg = h.change + (f" {h.change_ratio:+.1f}%" if h.change_ratio is not None else "")
        chg_cell = f'<span class="{style}">{chg}</span>' if style else chg
        tr.append(
            "<tr>"
            f"<td>{h.rank}</td><td style=\"text-align:left\">{h.name}</td>"
            f"<td>{h.share_type}</td>"
            f"<td>{_fmt_wan(h.hold_num)}</td>"
            f"<td>{h.ratio:.2f}%</td>" if h.ratio is not None else f"<td>-</td>"
            f"<td>{chg_cell}</td>"
            "</tr>"
        )
        md_rows.append(
            f"| {h.rank} | {h.name} | {h.share_type} | {_fmt_wan(h.hold_num)} | "
            f"{h.ratio:.2f}%" if h.ratio is not None else f"| {h.rank} | {h.name} | {h.share_type} | {_fmt_wan(h.hold_num)} | - |"
            + f" | {chg} |"
        )

    gtr = []
    gmd_rows = [
        "| 截止日 | 户数 | 环比 | 户均市值 | 户均持股 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in gdhs_rows[:8]:
        gtr.append(
            "<tr>"
            f"<td>{r.end_date}</td><td>{r.holder_num:,.0f}</td>"
            f"<td>{r.change_pct:+.1f}%" if r.change_pct is not None else "<td>-</td>"
            f"<td>{_fmt_wan(r.avg_market_cap)}</td>"
            f"<td>{r.avg_hold_num:,.0f}</td>"
            "</tr>"
        )
        gmd_rows.append(
            f"| {r.end_date} | {r.holder_num:,.0f} | "
            f"{r.change_pct:+.1f}%" if r.change_pct is not None else f"| {r.end_date} | {r.holder_num:,.0f} | - |"
            + f" | {_fmt_wan(r.avg_market_cap)} | {r.avg_hold_num:,.0f} |"
        )

    insight_html = "".join(f"<li>{x}</li>" for x in insights)
    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1080px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 24px 0 8px; }
.meta { color: #86909c; font-size: 12px; margin-bottom: 16px; }
.card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; }
th { background: #fafafa; color: #666; font-weight: 600; }
th:first-child, td:first-child { text-align: left; }
.up { color: #e02e24; } .down { color: #00a870; }
.insights li { margin: 4px 0; }
.footer { color: #86909c; font-size: 12px; text-align: center; padding: 16px 0 8px; }
"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>股东分析 {name}({code}) {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>股东分析：{name}（{code}）</h1>
<div class="meta">{as_of} · 报告期 {report_date} · 数据来源：东方财富 F10 / 数据中心 · 涨红跌绿</div>
<h2>解读</h2>
<div class="card"><ul class="insights">{insight_html if insight_html else '<li>数据不足</li>'}</ul></div>
<h2>十大股东（合计 {top_ratio:.1f}%）</h2>
<div class="card"><table>
<tr><th>名次</th><th style="text-align:left">股东名称</th><th>股份类型</th><th>持股数</th><th>占比</th><th>变动</th></tr>
{''.join(tr) if tr else '<tr><td colspan="6" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<h2>股东户数趋势（近 8 期）</h2>
<div class="card"><table>
<tr><th>截止日</th><th>户数</th><th>环比</th><th>户均市值</th><th>户均持股</th></tr>
{''.join(gtr) if gtr else '<tr><td colspan="5" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<div class="footer">股东分析为公开信息统计，不构成投资建议。市场有风险，投资需谨慎。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 股东分析 {name}({code}) {as_of}
date: {as_of}
tags: [股东, 十大股东, 筹码]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 股东分析：{name}（{code}）

报告期：{report_date}

## 解读

{chr(10).join(f"- {x}" for x in insights) if insights else "- 数据不足"}

## 十大股东（合计 {top_ratio:.1f}%）

{chr(10).join(md_rows) if md_rows else "无数据。"}

## 股东户数趋势（近 8 期）

{chr(10).join(gmd_rows) if gmd_rows else "无数据。"}

> 股东分析为公开信息统计，不构成投资建议。
"""
    return html, md
