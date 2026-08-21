"""行业景气监控：月度产销快报解析（车企先行指标）。

数据源：东财公告（"X月产销快报"标题，复用 announcements），
从标题/内容正则提取销量数字（万辆/台）。

当前支持：A 股车企月度产销快报（比亚迪等每月 1-2 号发布）。
提取：当月销量/产量（标题常见"X月产销快报：新能源汽车销量 XX 万辆"）。
入库 SQLite（sector_sales 表，代码+日期唯一）供趋势追踪。

说明：销量为月度先行指标，直接反映经营景气；解析为规则化提取，
提取失败时如实标注。不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

_SALES_RE = re.compile(
    r"(?:销量|销售)\s*[:：]?\s*([\d,]+\.?\d*)\s*(万辆|万台|辆|台)"
)
# 正文提取（标题无销量时，拉公告正文）
_BODY_SALES_RE = re.compile(
    r"(?:新能源汽车)?(?:销量|销售(?:量)?)[^0-9]{0,12}"
    r"([\d,]+\.?\d*)\s*(万辆|万台|辆|台)"
)
_MONTH_RE = re.compile(r"(\d{4})年(\d{1,2})月")


def _fetch_body(url: str) -> str:
    """拉取公告正文（东财内容 API，JSON 返回）。失败返回空。"""
    try:
        import requests

        resp = requests.get(
            url, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            }, timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()
        # 兼容不同返回结构
        content = data.get("data") or data
        if isinstance(content, dict):
            return str(content.get("notice_content")
                       or content.get("content") or "")
        return str(content)
    except Exception:  # noqa: BLE001
        return ""


@dataclass
class SalesReport:
    code: str
    name: str
    date: str           # 公告日期
    title: str
    month: str          # 报表月份 YYYY-MM
    sales: float | None     # 销量（万辆）
    sales_unit: str = "万辆"
    raw_sales: str = ""     # 提取原文

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "date": self.date,
            "title": self.title, "month": self.month,
            "sales": self.sales, "sales_unit": self.sales_unit,
            "raw_sales": self.raw_sales,
        }


def parse_sales(text: str) -> tuple[float | None, str, str]:
    """从文本（标题或正文）提取 (销量, 单位, 原文)。"""
    for pat in (_SALES_RE, _BODY_SALES_RE):
        m = pat.search(text)
        if m:
            num = float(m.group(1).replace(",", ""))
            unit = m.group(2)
            if unit in ("万辆", "万台"):
                return num, unit, m.group(0)
            return num, unit, m.group(0)
    return None, "", ""


def scan_sales(cfg, codes: list[str] | None = None,
               limit: int = 30) -> list[SalesReport]:
    """扫描自选股产销快报（标题含"产销快报"）。"""
    from .announcements import fetch_announcements

    items: list[SalesReport] = []
    for it in cfg.watchlist:
        if str(it.get("market", "ashare")) != "ashare":
            continue
        c = str(it["code"])
        if codes and c not in codes:
            continue
        name = str(it.get("name", c))
        try:
            anns = fetch_announcements(c, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("产销快报：%s 公告失败: %s", c, exc)
            continue
        for a in anns:
            if "产销快报" not in a["title"]:
                continue
            sales, unit, raw = parse_sales(a["title"])
            if sales is None and a.get("url"):
                # 标题无销量 → 拉正文提取（失败降级"未提取"）
                body = _fetch_body(a["url"])
                if body:
                    sales, unit, raw = parse_sales(body)
            # 月份：公告标题无月份时用公告日期所在月
            m = _MONTH_RE.search(a["title"])
            month = (f"{m.group(1)}-{int(m.group(2)):02d}" if m
                     else a["date"][:7])
            items.append(SalesReport(
                code=c, name=name, date=a["date"], title=a["title"],
                month=month, sales=sales, sales_unit=unit or "万辆",
                raw_sales=raw,
            ))
    items.sort(key=lambda x: x.month, reverse=True)
    return items


def save_sales(rows: list[SalesReport]) -> int:
    """入库（代码+月份唯一），返回新增。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    added = 0
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sector_sales (
                code TEXT, name TEXT, date TEXT, title TEXT,
                month TEXT, sales REAL, sales_unit TEXT, raw_sales TEXT,
                PRIMARY KEY (code, month))"""
        )
        for r in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO sector_sales "
                "(code, name, date, title, month, sales, sales_unit, raw_sales) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (r.code, r.name, r.date, r.title, r.month,
                 r.sales, r.sales_unit, r.raw_sales),
            )
            added += cur.rowcount
    return added


def build_sales_report(rows: list[SalesReport],
                       as_of: str | None = None) -> tuple[str, str]:
    """生成产销快报报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    tr = []
    md_rows = [
        "| 报表月 | 标的 | 销量 | 公告 |",
        "| --- | --- | --- | --- |",
    ]
    for x in rows:
        sales = (f"{x.sales:.2f} {x.sales_unit}" if x.sales is not None
                 else f"（{x.raw_sales or '未提取'}）")
        tr.append(
            "<tr>"
            f"<td>{x.month}</td><td>{x.name}({x.code})</td>"
            f"<td>{sales}</td>"
            f'<td style="text-align:left">{x.title[:40]}</td>'
            "</tr>"
        )
        md_rows.append(f"| {x.month} | {x.name}({x.code}) | {sales} | "
                       f"{x.title[:40]} |")

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
.footer { color: #86909c; font-size: 12px; text-align: center; padding: 16px 0 8px; }
"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>产销快报 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>月度产销快报（行业景气先行指标）</h1>
<div class="meta">{as_of} · 数据来源：东财公告 · 销量为规则化提取</div>
<div class="card"><table>
<tr><th>报表月</th><th>标的</th><th>销量</th><th style="text-align:left">公告</th></tr>
{''.join(tr) if tr else '<tr><td colspan="4" style="text-align:center;color:#86909c">近期无产销快报公告</td></tr>'}
</table></div>
<div class="footer">销量为月度先行指标；规则化提取失败时如实标注。不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 产销快报 {as_of}
date: {as_of}
tags: [销量, 景气]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 月度产销快报 {as_of}

{chr(10).join(md_rows) if md_rows else "近期无产销快报公告。"}

> 不构成投资建议。
"""
    return html, md
