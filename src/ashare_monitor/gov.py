"""政府侧企业动态：从中标/拿地/补助/税收优惠等公告监控企业-政府交互。

数据源：东财公告（fetch_announcements，标题关键词过滤）。
覆盖四类：
- 招投标：中标、竞得、竞买、采购、中标公告
- 拿地：土地使用权、地块、竞得土地
- 补助补贴：政府补助、专项资金、补贴、扶持
- 资质税收：税收优惠、高新技术企业、免税、纳入名单

如实说明：本命令为上市公司公告侧动态（公司主动披露）；完整的政府侧
明细数据（纳税信用等级、社保参保人数、招投标记录、拿地地块档案）需
企业数据库（天眼查/企查查/上奇产业通），免费公开源（政府采购网 403、
土地市场网 418、国家企业信用系统反爬）均不可用。

声明：公开信息整理，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# 关键词 → 分类
GOV_KEYWORDS: dict[str, list[str]] = {
    "招投标": ["中标", "竞得", "竞买", "采购", "成交"],
    "拿地": ["土地使用权", "地块", "竞得土地", "土地出让"],
    "补助补贴": ["政府补助", "专项资金", "补贴", "扶持", "补助"],
    "资质税收": ["税收优惠", "高新技术企业", "免税", "纳入名单", "专精特新"],
}


@dataclass
class GovItem:
    code: str
    name: str
    date: str
    title: str
    category: str       # 招投标/拿地/补助补贴/资质税收
    url: str = ""
    matched_kw: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "date": self.date,
            "title": self.title, "category": self.category,
            "url": self.url, "matched_kw": self.matched_kw,
        }


def classify_title(title: str) -> tuple[str, str] | None:
    """按标题关键词分类（最长关键词优先，如"土地使用权"优先于"竞得"）。

    返回 (分类, 命中关键词) 或 None。
    """
    best = None
    for cat, kws in GOV_KEYWORDS.items():
        for kw in kws:
            if kw in title and (best is None or len(kw) > len(best[1])):
                best = (cat, kw)
    return best


def scan_government_dynamics(cfg, codes: list[str] | None = None,
                             limit: int = 30) -> list[GovItem]:
    """扫描自选股公告中的政府侧动态。"""
    from .announcements import fetch_announcements

    items: list[GovItem] = []
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
            logger.warning("政府动态：%s 公告获取失败: %s", c, exc)
            continue
        for a in anns:
            cls = classify_title(a["title"])
            if not cls:
                continue
            cat, kw = cls
            items.append(GovItem(
                code=c, name=name, date=a["date"], title=a["title"],
                category=cat, url=a.get("url", ""), matched_kw=kw,
            ))
    items.sort(key=lambda x: (x.date, x.code), reverse=True)
    return items


def build_gov_report(items: list[GovItem], days: int,
                     as_of: str | None = None) -> tuple[str, str]:
    """生成政府动态报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _cls(cat: str) -> str:
        return {"招投标": "#1677ff", "拿地": "#e02e24",
                "补助补贴": "#00a870", "资质税收": "#b7950b"}.get(cat, "")

    tr = []
    md_rows = [
        "| 日期 | 标的 | 分类 | 公告 |",
        "| --- | --- | --- | --- |",
    ]
    for x in items:
        color = _cls(x.category)
        cat_cell = f'<span style="color:{color}">{x.category}</span>'
        title_cell = (f'<a href="{x.url}" target="_blank" '
                      f'style="color:#1677ff;text-decoration:none">{x.title}</a>'
                      if x.url else x.title)
        tr.append(
            "<tr>"
            f"<td>{x.date}</td><td>{x.name}({x.code})</td>"
            f"<td>{cat_cell}</td>"
            f'<td style="text-align:left">{title_cell}</td>'
            "</tr>"
        )
        md_rows.append(f"| {x.date} | {x.name}({x.code}) | {x.category} | "
                       f"[{x.title}]({x.url}) |" if x.url else
                       f"| {x.date} | {x.name}({x.code}) | {x.category} | {x.title} |")

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
<title>政府动态 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>政府侧企业动态（自选股公告）</h1>
<div class="meta">{as_of} · 数据来源：东财公告（标题关键词过滤）· 招投标/拿地/补助补贴/资质税收</div>
<div class="card"><table>
<tr><th>日期</th><th>标的</th><th>分类</th><th style="text-align:left">公告</th></tr>
{''.join(tr) if tr else '<tr><td colspan="4" style="text-align:center;color:#86909c">近期无政府相关公告</td></tr>'}
</table></div>
<div class="footer">为公告侧动态（公司主动披露）；完整政府数据（纳税信用/社保/招投标记录/拿地档案）
需企业数据库。不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 政府动态 {as_of}
date: {as_of}
tags: [政府, 招投标, 补助]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 政府侧企业动态（近 {days} 天）

{chr(10).join(md_rows) if md_rows else "近期无政府相关公告。"}

> 公告侧动态；完整政府数据需企业数据库，不构成投资建议。
"""
    return html, md
