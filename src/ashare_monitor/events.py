"""事件日历提醒：扫描自选股未来 N 天的重大事件。

数据源（东财数据中心直连）：
- 限售解禁：RPT_LIFT_STAGE（FREE_DATE）
- 分红除权：RPT_SHAREBONUS_DET（EX_DIVIDEND_DATE）
- 业绩预告：RPT_PUBLIC_OP_NEWPREDICT（NOTICE_DATE）

输出未来事件日历（按日期排序），供提前关注业绩雷/解禁压力/分红除权。

声明：事件为公开信息整理，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}


@dataclass
class CalendarEvent:
    code: str
    name: str
    market: str
    kind: str      # 解禁 / 分红除权 / 业绩预告
    date: str      # 事件日期 YYYY-MM-DD
    detail: str    # 事件说明
    source: str = "东财数据中心"

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "market": self.market,
            "kind": self.kind, "date": self.date, "detail": self.detail,
            "source": self.source,
        }


def _query(report_name: str, filter_s: str, sort_col: str,
           page_size: int = 20) -> list[dict]:
    resp = requests.get(
        _API,
        params={
            "reportName": report_name,
            "columns": "ALL",
            "pageSize": page_size, "pageNumber": 1,
            "filter": filter_s,
            "sortColumns": sort_col, "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        },
        headers=_HEADERS, timeout=12,
    )
    resp.raise_for_status()
    return (resp.json().get("result") or {}).get("data") or []


def _is_hk(code: str) -> bool:
    return len(code) == 5 and code.isdigit()


def fetch_events(code: str, market: str, days: int = 30) -> list[CalendarEvent]:
    """查询单只标未来 days 天的事件。"""
    events: list[CalendarEvent] = []
    today = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    if market == "hk":
        return events  # 港股暂无解禁/分红日历接口，返回空
    code6 = code[-6:]
    name = ""

    # 1. 限售解禁
    try:
        rows = _query("RPT_LIFT_STAGE", f'(SECURITY_CODE="{code6}")', "FREE_DATE")
        for x in rows:
            d = str(x.get("FREE_DATE") or "")[:10]
            if today <= d <= end:
                name = str(x.get("SECURITY_NAME_ABBR") or name or code)
                cap = float(x.get("LIFT_MARKET_CAP") or 0) / 1e4  # 万→亿
                ratio = x.get("FREE_RATIO")
                detail = (
                    f"{x.get('FREE_SHARES_TYPE') or '限售解禁'}，解禁市值约 "
                    f"{cap:.1f} 亿" + (f"，占总股本 {float(ratio):.1f}%" if ratio else "")
                )
                events.append(CalendarEvent(code, name, market, "解禁", d, detail))
    except Exception as exc:  # noqa: BLE001
        logger.warning("事件：%s 解禁查询失败: %s", code, exc)

    # 2. 分红除权
    try:
        rows = _query("RPT_SHAREBONUS_DET", f'(SECURITY_CODE="{code6}")',
                      "PLAN_NOTICE_DATE", page_size=8)
        for x in rows:
            d = str(x.get("EX_DIVIDEND_DATE") or "")[:10]
            if today <= d <= end:
                name = str(x.get("SECURITY_NAME_ABBR") or name or code)
                bonus = x.get("BONUS_RATIO")   # 每 10 股派息
                it = x.get("IT_RATIO")         # 每 10 股转增
                parts = [f"{x.get('REPORT_DATE', '')[:10]} 年度利润分配"]
                if bonus:
                    parts.append(f"10 派 {float(bonus):g}")
                if it:
                    parts.append(f"10 转 {float(it):g}")
                events.append(CalendarEvent(
                    code, name, market, "分红除权", d, "、".join(parts),
                ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("事件：%s 分红查询失败: %s", code, exc)

    # 3. 业绩预告
    try:
        rows = _query("RPT_PUBLIC_OP_NEWPREDICT", f'(SECURITY_CODE="{code6}")',
                      "NOTICE_DATE", page_size=8)
        seen = set()
        for x in rows:
            d = str(x.get("NOTICE_DATE") or "")[:10]
            if today <= d <= end and (code, d) not in seen:
                seen.add((code, d))
                name = str(x.get("SECURITY_NAME_ABBR") or name or code)
                ptype = x.get("PREDICT_TYPE") or "业绩预告"
                pf = x.get("PREDICT_FINANCE") or ""
                detail = f"{x.get('REPORT_DATE', '')[:10]} 报告期{ptype}"
                events.append(CalendarEvent(
                    code, name, market, "业绩预告", d, detail,
                ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("事件：%s 业绩预告查询失败: %s", code, exc)

    return events


def scan_events(cfg, codes: list[str] | None = None,
                days: int = 30) -> list[CalendarEvent]:
    """扫描自选股（或指定代码）未来 days 天事件。"""
    all_events: list[CalendarEvent] = []
    for item in cfg.watchlist:
        market = str(item.get("market", "ashare"))
        if market == "crypto":
            continue
        code = str(item["code"])
        if codes and code not in codes:
            continue
        try:
            all_events.extend(fetch_events(code, market, days))
        except Exception as exc:  # noqa: BLE001
            logger.warning("事件扫描：%s 失败: %s", code, exc)
    all_events.sort(key=lambda e: (e.date, e.code))
    return all_events


# ---------- 报告 ----------

def build_events_report(events: list[CalendarEvent], days: int = 30,
                        as_of: str | None = None) -> tuple[str, str]:
    """生成事件日历报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _cls(kind: str) -> str:
        return {"解禁": "#e02e24", "分红除权": "#1677ff", "业绩预告": "#faad14"}.get(kind, "")

    tr = []
    md_rows = [
        "| 日期 | 标的 | 类型 | 事件 |",
        "| --- | --- | --- | --- |",
    ]
    for e in events:
        color = _cls(e.kind)
        kind_cell = f'<span class="tag" style="color:{color}">{e.kind}</span>'
        tr.append(
            "<tr>"
            f"<td>{e.date}</td><td>{e.name}({e.code})</td>"
            f"<td>{kind_cell}</td>"
            f'<td style="text-align:left">{e.detail}</td>'
            "</tr>"
        )
        md_rows.append(f"| {e.date} | {e.name}({e.code}) | {e.kind} | {e.detail} |")

    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1080px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
.meta { color: #86909c; font-size: 12px; margin-bottom: 16px; }
.card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; }
th { background: #fafafa; color: #666; font-weight: 600; }
th:first-child, td:first-child { text-align: left; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; background: #f0f0f0; }
.footer { color: #86909c; font-size: 12px; text-align: center; padding: 16px 0 8px; }
"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>事件日历 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>事件日历提醒</h1>
<div class="meta">{as_of} · 未来 {days} 天 · 解禁 / 分红除权 / 业绩预告 · 数据来源：东财数据中心</div>
<div class="card"><table>
<tr><th>日期</th><th>标的</th><th>类型</th><th style="text-align:left">事件</th></tr>
{''.join(tr) if tr else '<tr><td colspan="4" style="text-align:center;color:#86909c">未来无事件</td></tr>'}
</table></div>
<div class="footer">事件为公开信息整理，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 事件日历 {as_of}
date: {as_of}
tags: [事件, 日历]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 事件日历提醒（未来 {days} 天）

{chr(10).join(md_rows) if md_rows else "未来无事件。"}

> 事件为公开信息整理，不构成投资建议。
"""
    return html, md
