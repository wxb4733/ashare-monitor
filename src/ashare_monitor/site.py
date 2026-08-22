"""官方网站链接档案 + 官网公告监控。

- 官方链接：工商档案（巨潮）自动获取官网 + config.local.yaml 的 `sites` 段扩展
  （code -> {website, ir_url, notice_url, social}）
- 官网公告监控：对配置了 notice_url 的公司尝试抓取公告列表（标题+链接）；
  实测多数官网公告页为 JS 动态加载（如 CATL /investor/notice/ 仅返回壳页），
  抓取失败时如实提示"动态加载不可自动抓取"，保留公告页链接供人工查看。

权威官方公告（沪深交易所披露）仍以东财公告（announcements 模块）为准——
官网公告为其同源转载，本模块补充官网特有的新闻/产品动态。

声明：公开信息整理，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}

# 内置官网（缺省用工商档案 website；此处仅补充公告页）
DEFAULT_SITES: dict[str, dict] = {
    "300750": {"notice_url": "https://www.catl.com/investor/notice/"},
    "600519": {"website": "https://www.moutai.com.cn/"},
    "01810": {"website": "https://www.mi.com/",
              "notice_url": "https://www.hkexnews.hk/search/titlesearch.xhtml"},
}


@dataclass
class SiteLinks:
    code: str
    name: str
    website: str = ""
    ir_url: str = ""
    notice_url: str = ""
    social: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "website": self.website,
            "ir_url": self.ir_url, "notice_url": self.notice_url,
            "social": self.social, "sources": self.sources,
        }


@dataclass
class SiteNotice:
    code: str
    name: str
    title: str
    url: str
    date: str            # 抓取日（页面无日期时）
    source: str = "官网"

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "title": self.title,
            "url": self.url, "date": self.date, "source": self.source,
        }


def site_links(cfg, code: str, name: str = "") -> SiteLinks:
    """聚合官网链接：config sites 段 > 内置表 > 工商档案。"""
    sl = SiteLinks(code=code, name=name or code)
    extra = (getattr(cfg, "sites", None) or {}) if hasattr(cfg, "sites") else {}
    if not isinstance(extra, dict):
        extra = {}
    merged = dict(DEFAULT_SITES.get(code, {}))
    merged.update(extra.get(code, {}) or {})
    for k in ("website", "ir_url", "notice_url", "social"):
        v = merged.get(k)
        if v:
            setattr(sl, k, str(v))
            sl.sources.append("config" if k in (extra.get(code) or {}) else "内置")
    # 工商档案兜底官网
    if not sl.website and code.isdigit() and len(code) == 6:
        try:
            from .profile import fetch_profile

            p = fetch_profile(code, "ashare")
            if p.website:
                sl.website = p.website
                sl.sources.append("工商档案")
        except Exception:  # noqa: BLE001
            pass
    return sl


def fetch_site_notices(sl: SiteLinks, limit: int = 20) -> tuple[list[SiteNotice], str]:
    """抓取官网公告页（配置了 notice_url 时）。返回 (公告列表, 状态说明)。"""
    if not sl.notice_url:
        return [], "未配置公告页地址"
    try:
        resp = requests.get(sl.notice_url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return [], f"公告页访问失败：{exc}"
    html = resp.text
    # 提取标题+链接（含关键词过滤：公告/通知/披露/新闻/报告）
    items = re.findall(
        r'<a[^>]+href="([^"]+)"[^>]*>([^<]{4,80})</a>', html)
    hits = []
    for url, title in items:
        title = re.sub(r"\s+", " ", title).strip()
        if not title or not re.search(r"公告|通知|披露|新闻|报告|公示|通函",
                                      title):
            continue
        if url.startswith("javascript"):
            continue
        from urllib.parse import urljoin

        full = url if url.startswith("http") else urljoin(sl.notice_url, url)
        hits.append(SiteNotice(
            code=sl.code, name=sl.name, title=title, url=full,
            date=datetime.now().strftime("%Y-%m-%d"),
        ))
        if len(hits) >= limit:
            break
    if not hits:
        return [], "公告页为动态加载或无可解析条目（请从公告页链接人工查看）"
    return hits, "ok"


def build_site_report(links_list: list[SiteLinks], notices: list[SiteNotice],
                      as_of: str | None = None) -> tuple[str, str]:
    """生成官网档案报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    tr = []
    md_rows = [
        "| 标的 | 官网 | 公告页 | 其他链接 |",
        "| --- | --- | --- | --- |",
    ]
    for s in links_list:
        def _lbl(u: str) -> str:
            return (f'<a href="{u}" target="_blank" style="color:#1677ff;'
                    f'text-decoration:none">{u[:35]}</a>') if u else "-"
        tr.append(
            "<tr>"
            f"<td>{s.name}({s.code})</td>"
            f'<td style="text-align:left">{_lbl(s.website)}</td>'
            f'<td style="text-align:left">{_lbl(s.notice_url)}</td>'
            f'<td style="text-align:left">{_lbl(s.ir_url or s.social)}</td>'
            "</tr>"
        )
        md_rows.append(f"| {s.name}({s.code}) | [{s.website}]({s.website}) | "
                       f"[{s.notice_url}]({s.notice_url}) | "
                       f"[{s.ir_url or s.social}]({s.ir_url or s.social}) |")

    ntr = []
    nmd_rows = [
        "| 日期 | 标的 | 标题 |",
        "| --- | --- | --- |",
    ]
    for n in notices:
        ntr.append(
            "<tr>"
            f"<td>{n.date}</td><td>{n.name}({n.code})</td>"
            f'<td style="text-align:left"><a href="{n.url}" target="_blank" '
            f'style="color:#1677ff;text-decoration:none">{n.title}</a></td>'
            "</tr>"
        )
        nmd_rows.append(f"| {n.date} | {n.name}({n.code}) | [{n.title}]({n.url}) |")

    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1080px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 20px 0 8px; }
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
<title>官网档案与公告 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>官方网站链接与公告监控</h1>
<div class="meta">{as_of} · 官网来源：工商档案/config · 公告抓取：配置的公告页（动态加载页如实提示）</div>
<h2>官方链接档案</h2>
<div class="card"><table>
<tr><th>标的</th><th style="text-align:left">官网</th><th style="text-align:left">公告页</th><th style="text-align:left">其他</th></tr>
{''.join(tr) if tr else '<tr><td colspan="4" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<h2>官网公告抓取</h2>
<div class="card"><table>
<tr><th>日期</th><th>标的</th><th style="text-align:left">标题</th></tr>
{''.join(ntr) if ntr else '<tr><td colspan="3" style="text-align:center;color:#86909c">无可解析公告（多数官网公告页为 JS 动态加载）</td></tr>'}
</table></div>
<div class="footer">权威官方公告以东财公告（交易所披露）为准；官网补充新闻/产品动态。不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 官网档案与公告 {as_of}
date: {as_of}
tags: [官网, 公告]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 官方网站链接与公告监控

## 官方链接档案

{chr(10).join(md_rows) if md_rows else "无数据。"}

## 官网公告抓取

{chr(10).join(nmd_rows) if nmd_rows else "无可解析公告（多数官网公告页为 JS 动态加载）。"}

> 权威官方公告以东财公告为准，不构成投资建议。
"""
    return html, md
