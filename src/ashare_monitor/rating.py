"""研报评级监控：券商研报（含盈利预测）跟踪。

数据源：东财研报（复用 announcements.fetch_research_reports）。
字段：日期/标题/机构/当年 EPS 预测/当年 PE 预测。
过滤自选股，入库 SQLite（rating 表，url 去重）。

用途：研报密度与机构覆盖反映市场关注度；EPS 预测变化 → 盈利预期修正。
不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Rating:
    code: str
    name: str
    date: str
    title: str
    org: str
    eps_this_year: float | None
    pe_this_year: float | None
    url: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "date": self.date,
            "title": self.title, "org": self.org,
            "eps_this_year": self.eps_this_year, "pe_this_year": self.pe_this_year,
            "url": self.url,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def scan_ratings(cfg, codes: list[str] | None = None,
                 days: int = 30, limit: int = 10) -> list[Rating]:
    """扫描自选股研报。"""
    from .announcements import fetch_research_reports

    items: list[Rating] = []
    for it in cfg.watchlist:
        market = str(it.get("market", "ashare"))
        if market != "ashare":
            continue
        c = str(it["code"])
        if codes and c not in codes:
            continue
        name = str(it.get("name", c))
        try:
            reps = fetch_research_reports(c, days=days, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("研报扫描：%s 失败: %s", c, exc)
            continue
        for r in reps:
            items.append(Rating(
                code=c, name=name, date=r.get("date", ""),
                title=r.get("title", ""), org=r.get("org", ""),
                eps_this_year=_f(r.get("eps_this_year")),
                pe_this_year=_f(r.get("pe_this_year")),
                url=r.get("url", ""),
            ))
    items.sort(key=lambda x: (x.date, x.code), reverse=True)
    return items


def save_ratings(rows: list[Rating]) -> int:
    """入库去重（url 唯一）。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    added = 0
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS rating (
                code TEXT, name TEXT, date TEXT, title TEXT, org TEXT,
                eps_this_year REAL, pe_this_year REAL,
                url TEXT PRIMARY KEY)"""
        )
        for r in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO rating "
                "(code, name, date, title, org, eps_this_year, pe_this_year, url) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (r.code, r.name, r.date, r.title, r.org,
                 r.eps_this_year, r.pe_this_year, r.url),
            )
            added += cur.rowcount
    return added


def build_rating_report(rows: list[Rating],
                        as_of: str | None = None) -> tuple[str, str]:
    """生成研报监控报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    tr = []
    md_rows = [
        "| 日期 | 标的 | 机构 | 标题 | EPS预测 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for x in rows:
        eps = f"{x.eps_this_year:.2f}" if x.eps_this_year is not None else "-"
        tr.append(
            "<tr>"
            f"<td>{x.date}</td><td>{x.name}({x.code})</td>"
            f"<td>{x.org}</td>"
            f'<td style="text-align:left"><a href="{x.url}" target="_blank" '
            f'style="color:#1677ff;text-decoration:none">{x.title[:40]}</a></td>'
            f"<td>{eps}</td>"
            "</tr>"
        )
        md_rows.append(f"| {x.date} | {x.name}({x.code}) | {x.org} | "
                       f"[{x.title[:40]}]({x.url}) | {eps} |")

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
<title>研报监控 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>券商研报监控（自选股）</h1>
<div class="meta">{as_of} · 数据来源：东财研报</div>
<div class="card"><table>
<tr><th>日期</th><th>标的</th><th>机构</th><th style="text-align:left">标题</th><th>EPS预测</th></tr>
{''.join(tr) if tr else '<tr><td colspan="5" style="text-align:center;color:#86909c">近期无研报</td></tr>'}
</table></div>
<div class="footer">研报密度反映市场关注度；EPS 预测变化 → 盈利预期修正。不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 研报监控 {as_of}
date: {as_of}
tags: [研报, 评级]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 券商研报监控 {as_of}

{chr(10).join(md_rows) if md_rows else "近期无研报。"}

> 不构成投资建议。
"""
    return html, md
