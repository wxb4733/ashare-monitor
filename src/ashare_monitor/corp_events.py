"""增减持与回购监控：董监高/大股东减持增持 + 公司回购公告。

数据源：东财公告（标题关键词过滤，复用 announcements）。
信号：减持/减持计划（利空）、增持/增持计划（利好）、回购（利好，真金白银）。
入库 SQLite（insider_events 表，url 去重）供历史追踪与推送。

说明：公告级信号（公司主动披露）；高频逐笔增减持明细数据量大，
以公告为准更可靠。不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# 关键词 → 信号类型
EVENT_KEYWORDS: dict[str, list[str]] = {
    "减持": ["减持", "减持计划", "被动减持", "拟减持"],
    "增持": ["增持", "增持计划", "增持股份", "拟增持"],
    "回购": ["回购", "注销", "回购股份", "回购方案"],
}

# 数字提取（用于产销快报/减持数量，宽松）
_NUM = re.compile(r"([\d,]+\.?\d*)\s*(万辆|万辆|台|股|万股|亿元|亿元|%|亿|万)?")


@dataclass
class CorpEvent:
    code: str
    name: str
    date: str
    title: str
    event_type: str    # 减持/增持/回购
    url: str = ""
    matched_kw: str = ""
    note: str = ""     # 提取的数字等

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "date": self.date,
            "title": self.title, "event_type": self.event_type,
            "url": self.url, "matched_kw": self.matched_kw, "note": self.note,
        }


def classify_event(title: str) -> tuple[str, str] | None:
    """按标题关键词分类（最长优先）。"""
    best = None
    for etype, kws in EVENT_KEYWORDS.items():
        for kw in kws:
            if kw in title and (best is None or len(kw) > len(best[1])):
                best = (etype, kw)
    return best


def scan_corp_events(cfg, codes: list[str] | None = None,
                     limit: int = 30) -> list[CorpEvent]:
    """扫描自选股公告中的增减持/回购事件。"""
    from .announcements import fetch_announcements

    items: list[CorpEvent] = []
    for it in cfg.watchlist:
        market = str(it.get("market", "ashare"))
        if market != "ashare":
            continue
        c = str(it["code"])
        if codes and c not in codes:
            continue
        name = str(it.get("name", c))
        try:
            anns = fetch_announcements(c, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("增减持扫描：%s 公告失败: %s", c, exc)
            continue
        for a in anns:
            cls = classify_event(a["title"])
            if not cls:
                continue
            etype, kw = cls
            note = ""
            m = _NUM.search(a["title"])
            if m and m.group(1):
                note = m.group(0)
            items.append(CorpEvent(
                code=c, name=name, date=a["date"], title=a["title"],
                event_type=etype, url=a.get("url", ""),
                matched_kw=kw, note=note,
            ))
    items.sort(key=lambda x: (x.date, x.code), reverse=True)
    return items


def save_corp_events(rows: list[CorpEvent]) -> int:
    """入库去重（url 唯一），返回新增。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    added = 0
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS insider_events (
                code TEXT, name TEXT, date TEXT, title TEXT,
                event_type TEXT, url TEXT PRIMARY KEY,
                matched_kw TEXT, note TEXT)"""
        )
        for r in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO insider_events "
                "(code, name, date, title, event_type, url, matched_kw, note) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (r.code, r.name, r.date, r.title, r.event_type,
                 r.url, r.matched_kw, r.note),
            )
            added += cur.rowcount
    return added


def load_saved_events(limit: int = 50) -> list[CorpEvent]:
    """读取已入库事件（最新在前）。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = []
    for r in conn.execute(
        "SELECT * FROM insider_events ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall():
        rows.append(CorpEvent(
            code=r["code"], name=r["name"], date=r["date"],
            title=r["title"], event_type=r["event_type"],
            url=r["url"], matched_kw=r["matched_kw"], note=r["note"],
        ))
    return rows


def build_corp_report(rows: list[CorpEvent],
                      as_of: str | None = None) -> tuple[str, str]:
    """生成增减持/回购事件报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _cls(t: str) -> str:
        return {"减持": "#00a870", "增持": "#e02e24", "回购": "#1677ff"}.get(t, "")

    tr = []
    md_rows = [
        "| 日期 | 标的 | 类型 | 标题 |",
        "| --- | --- | --- | --- |",
    ]
    for x in rows:
        color = _cls(x.event_type)
        type_cell = f'<span style="color:{color}">{x.event_type}</span>'
        title_cell = (f'<a href="{x.url}" target="_blank" '
                      f'style="color:#1677ff;text-decoration:none">{x.title}</a>'
                      if x.url else x.title)
        tr.append(
            "<tr>"
            f"<td>{x.date}</td><td>{x.name}({x.code})</td>"
            f"<td>{type_cell}</td>"
            f'<td style="text-align:left">{title_cell}</td>'
            "</tr>"
        )
        md_rows.append(f"| {x.date} | {x.name}({x.code}) | {x.event_type} | "
                       f"[{x.title}]({x.url}) |" if x.url else
                       f"| {x.date} | {x.name}({x.code}) | {x.event_type} | {x.title} |")

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
<title>增减持与回购 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>增减持与回购监控</h1>
<div class="meta">{as_of} · 数据来源：东财公告（标题关键词）· 减持(绿)/增持(红)/回购(蓝)</div>
<div class="card"><table>
<tr><th>日期</th><th>标的</th><th>类型</th><th style="text-align:left">标题</th></tr>
{''.join(tr) if tr else '<tr><td colspan="4" style="text-align:center;color:#86909c">近期无增减持/回购公告</td></tr>'}
</table></div>
<div class="footer">公告级信号（公司主动披露），不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 增减持与回购 {as_of}
date: {as_of}
tags: [增减持, 回购, 信号]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 增减持与回购监控 {as_of}

{chr(10).join(md_rows) if md_rows else "近期无增减持/回购公告。"}

> 公告级信号，不构成投资建议。
"""
    return html, md
