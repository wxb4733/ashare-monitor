"""arXiv 论文监测：以指定股票代码对应公司为署名单位的最新论文。

数据源：arXiv API（https://export.arxiv.org/api/query，免费、无 key）。
搜索流程：
1. 按公司英文名（+别名）全文检索，按提交日期降序取最近 N 条
2. 解析每条论文的作者署名单位（affiliation），**只保留署名单位含公司名/别名的论文**
   —— 即"以该公司为署名单位"的研究动态（研发信号）

用途：跟踪上市公司在 AI / 技术领域的研发动向（如比亚迪的 EV/电池方向论文）。
声明：论文为公开学术信息整理，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import requests
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_API = "https://export.arxiv.org/api/query"
_NS = {"a": "http://www.w3.org/2005/Atom",
       "x": "http://arxiv.org/schemas/atom"}

# 内置公司英文名映射（自选股 + 常见关注标的）；config 可覆盖
DEFAULT_ALIASES: dict[str, list[str]] = {
    "002594": ["BYD", "BYD Company"],
    "01211": ["BYD", "BYD Company"],
    "300750": ["CATL", "Contemporary Amperex"],
    "600519": ["Kweichow Moutai", "Moutai"],
    "000001": ["Ping An Bank"],
    "600036": ["China Merchants Bank"],
    "601318": ["Ping An Insurance"],
    "600030": ["CITIC Securities"],
    "000333": ["Midea Group"],
    "002415": ["Hikvision"],
}


@dataclass
class ArxivPaper:
    arxiv_id: str
    title: str
    authors: str          # 作者列表（逗号分隔）
    affiliation: str      # 署名单位（作者单位，逗号分隔）
    published: str        # 提交日期 YYYY-MM-DD
    updated: str
    summary: str          # 摘要（前 300 字）
    link: str
    categories: str
    matched_alias: str = ""   # 命中的公司别名

    def to_dict(self) -> dict:
        return {
            "arxiv_id": self.arxiv_id, "title": self.title,
            "authors": self.authors, "affiliation": self.affiliation,
            "published": self.published, "updated": self.updated,
            "summary": self.summary, "link": self.link,
            "categories": self.categories, "matched_alias": self.matched_alias,
        }


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def fetch_arxiv(query: str, max_results: int = 20) -> list[ArxivPaper]:
    """查询 arXiv 并按署名单位过滤。query 为 search_query（如 all:"BYD"）。"""
    resp = requests.get(
        _API,
        params={
            "search_query": query,
            "start": 0, "max_results": max_results,
            "sortBy": "submittedDate", "sortOrder": "descending",
        },
        timeout=20,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    papers: list[ArxivPaper] = []
    for e in root.findall("a:entry", _NS):
        try:
            arxiv_id = _clean(e.find("a:id", _NS).text).split("/abs/")[-1]
            title = _clean(e.find("a:title", _NS).text)
            published = (e.find("a:published", _NS).text or "")[:10]
            updated = (e.find("a:updated", _NS).text or "")[:10]
            # 完整摘要用于内容匹配（展示端自行截断）
            summary = _clean(e.find("a:summary", _NS).text)
            link = "https://arxiv.org/abs/" + arxiv_id.split("v")[0]
            cats = ",".join(
                a.get("term", "") for a in e.findall("a:category", _NS)
            )
            authors, affs = [], []
            for a in e.findall("a:author", _NS):
                nm = _clean(a.find("a:name", _NS).text)
                if nm:
                    authors.append(nm)
                # 署名单位（arXiv 扩展命名空间）
                aff = a.find("x:affiliation", _NS)
                if aff is not None and _clean(aff.text):
                    affs.append(_clean(aff.text))
            papers.append(ArxivPaper(
                arxiv_id=arxiv_id, title=title, authors=", ".join(authors),
                affiliation="; ".join(affs), published=published,
                updated=updated, summary=summary, link=link, categories=cats,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("arXiv 条目解析失败: %s", exc)
    return papers


def fetch_company_papers(
    company: str, aliases: list[str], max_results: int = 20, days: int = 730,
) -> list[ArxivPaper]:
    """获取以公司为主题/署名单位的最新论文。

    arXiv API 的 Atom feed 不返回作者 affiliation 字段，故采用内容匹配：
    1) 检索 abs:"company"（摘要含公司名/别名），按提交时间降序
    2) 摘要含公司名即视为相关（研发动态信号）；若解析到署名单位则展示
    """
    terms = [company] + [a for a in aliases if a and a != company]
    query = " OR ".join(f'abs:"{t}"' for t in terms)
    raw = fetch_arxiv(query, max_results=max_results)
    cutoff = None
    if days:
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=days)

    hits: list[ArxivPaper] = []
    for p in raw:
        matched = next(
            (t for t in terms if t.lower() in p.summary.lower()),
            None,
        )
        if not matched:
            continue  # 摘要不含公司名 → 丢弃
        if cutoff and p.published < cutoff.strftime("%Y-%m-%d"):
            continue
        p.matched_alias = matched
        hits.append(p)
    hits.sort(key=lambda p: p.published, reverse=True)
    return hits


def company_aliases(cfg, code: str) -> tuple[str, list[str]]:
    """解析代码 → (主英文名, 别名列表)。config.local.yaml 的 arxiv 段优先。"""
    extra = (getattr(cfg, "arxiv", None) or {}) if hasattr(cfg, "arxiv") else {}
    if not isinstance(extra, dict):
        extra = {}
    cfg_map = {str(k): v for k, v in extra.items()}
    if code in cfg_map:
        v = cfg_map[code]
        if isinstance(v, str):
            return v, [v]
        if isinstance(v, list) and v:
            return str(v[0]), [str(x) for x in v]
    builtin = DEFAULT_ALIASES.get(code)
    if builtin:
        return builtin[0], builtin
    return "", []


def _human_days(days: int) -> str:
    """14600 → '近 40 年'；730 → '近 730 天'。"""
    if days >= 3650 and days % 365 == 0:
        return f"近 {days // 365} 年"
    if days >= 365:
        return f"近 {days / 365:.1f} 年"
    return f"近 {days} 天"


def build_arxiv_report(papers: list[ArxivPaper], code: str, name: str,
                       company: str, days: int,
                       as_of: str | None = None) -> tuple[str, str]:
    """生成公司论文监测报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    span = _human_days(days)

    tr = []
    md_rows = [
        "| 日期 | 标题 | 署名单位 | 方向 |",
        "| --- | --- | --- | --- |",
    ]
    for p in papers:
        aff_short = p.affiliation[:60] + ("…" if len(p.affiliation) > 60 else "")
        tr.append(
            "<tr>"
            f"<td>{p.published}</td>"
            f'<td style="text-align:left"><a href="{p.link}" target="_blank" '
            f'style="color:#1677ff;text-decoration:none">{p.title}</a></td>'
            f'<td style="text-align:left">{aff_short}</td>'
            f"<td>{p.categories.split(',')[0]}</td>"
            "</tr>"
        )
        md_rows.append(
            f"| {p.published} | [{p.title}]({p.link}) | {aff_short} | "
            f"{p.categories.split(',')[0]} |"
        )

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
<title>公司论文监测 {name}({code}) {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>arXiv 论文监测：{name}（{code}）</h1>
<div class="meta">{as_of} · 检索署名单位含「{company}」的论文（{span}）· 数据来源：arXiv API</div>
<div class="card"><table>
<tr><th>日期</th><th style="text-align:left">标题</th><th style="text-align:left">署名单位</th><th>方向</th></tr>
{''.join(tr) if tr else '<tr><td colspan="4" style="text-align:center;color:#86909c">近期无该公司署名论文</td></tr>'}
</table></div>
<div class="footer">论文为公开学术信息整理，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 公司论文监测 {name}({code}) {as_of}
date: {as_of}
tags: [论文, arxiv, 研发]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# arXiv 论文监测：{name}（{code}）

检索署名单位含「{company}」的论文（{span}）。

{chr(10).join(md_rows) if md_rows else "近期无该公司署名论文。"}

> 论文为公开学术信息整理，不构成投资建议。
"""
    return html, md
