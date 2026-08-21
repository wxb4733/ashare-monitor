"""Hugging Face 模型与论文监测：以指定股票代码对应公司为单位。

数据源：Hugging Face API（默认 hf-mirror.com 国内镜像，可设 HF_ENDPOINT 覆盖）
- 模型：/api/models?author={org}（按组织，最近更新排序）
- 论文：/api/papers?search={company}（HF 收录的 AI 论文，含 arXiv 关联）

用途：跟踪上市公司 AI 研发动态的另一个维度（模型发布 / 论文收录）。
注意：A 股公司多在 HF 无组织账号（如实显示）；港股/科技公司如腾讯、阿里、
字节、百度、华为等有活跃账号。

声明：公开信息整理，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")

# 内置组织映射（code -> [org, 公司英文名]）；config 的 hf 段可覆盖
DEFAULT_ORGS: dict[str, list[str]] = {
    "00700": ["tencent", "Tencent"],
    "09988": ["Qwen", "Alibaba"],
    "03690": ["bytedance-research", "ByteDance"],
    "09888": ["baidu", "Baidu"],
    "09999": ["NetEase", "NetEase"],
    "000858": ["", "Wuliangye"],   # 无 HF 组织（如实）
    "300750": ["", "CATL"],
    "002594": ["", "BYD"],
    "600519": ["", "Kweichow Moutai"],
}

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


@dataclass
class HFModel:
    id: str
    last_modified: str
    downloads: int
    likes: int
    pipeline_tag: str
    tags: list[str]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "last_modified": self.last_modified,
            "downloads": self.downloads, "likes": self.likes,
            "pipeline_tag": self.pipeline_tag, "tags": self.tags,
        }


@dataclass
class HFPaper:
    arxiv_id: str
    title: str
    published: str
    authors: str
    upvotes: int
    summary: str
    organization: str
    link: str

    def to_dict(self) -> dict:
        return {
            "arxiv_id": self.arxiv_id, "title": self.title,
            "published": self.published, "authors": self.authors,
            "upvotes": self.upvotes, "summary": self.summary,
            "organization": self.organization, "link": self.link,
        }


def _get(path: str, params: dict) -> list:
    resp = requests.get(_ENDPOINT + path, params=params,
                        headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def fetch_models(org: str, limit: int = 10) -> list[HFModel]:
    """查询组织最新模型。org 为空返回空。"""
    if not org:
        return []
    rows = _get("/api/models", {
        "author": org, "sort": "lastModified", "direction": -1,
        "limit": limit,
    })
    models = []
    for m in rows:
        models.append(HFModel(
            id=str(m.get("id") or ""),
            last_modified=str(m.get("lastModified") or "")[:10],
            downloads=int(m.get("downloads") or 0),
            likes=int(m.get("likes") or 0),
            pipeline_tag=str(m.get("pipeline_tag") or ""),
            tags=[str(t) for t in (m.get("tags") or [])[:5]],
        ))
    return models


def fetch_papers(company: str, limit: int = 10) -> list[HFPaper]:
    """搜索 HF 收录的论文（按公司名）。"""
    rows = _get("/api/papers", {"search": company, "limit": limit})
    papers = []
    for p in rows:
        papers.append(HFPaper(
            arxiv_id=str(p.get("id") or ""),
            title=str(p.get("title") or ""),
            published=str(p.get("publishedAt") or "")[:10],
            authors=", ".join(a.get("name", "") for a in p.get("authors") or []),
            upvotes=int(p.get("upvotes") or 0),
            summary=str(p.get("summary") or "")[:200],
            organization=str(p.get("organization") or ""),
            link=f"https://huggingface.co/papers/{p.get('id')}",
        ))
    return papers


def orgs_for(cfg, code: str) -> tuple[str, str]:
    """解析代码 → (org, 公司英文名)。config 的 hf 段优先。"""
    extra = (getattr(cfg, "hf", None) or {}) if hasattr(cfg, "hf") else {}
    if not isinstance(extra, dict):
        extra = {}
    cfg_map = {str(k): v for k, v in extra.items()}
    if code in cfg_map:
        v = cfg_map[code]
        if isinstance(v, str):
            return v, v
        if isinstance(v, list) and v:
            return str(v[0]), str(v[1]) if len(v) > 1 else str(v[0])
    builtin = DEFAULT_ORGS.get(code)
    if builtin:
        return builtin[0], builtin[1]
    return "", ""


def build_hf_report(
    code: str, name: str, org: str, company: str,
    models: list[HFModel], papers: list[HFPaper],
    as_of: str | None = None,
) -> tuple[str, str]:
    """生成 HF 监测报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    tr = []
    md_rows = [
        "| 模型 | 更新 | 下载 | 点赞 | 任务 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for m in models:
        tr.append(
            "<tr>"
            f'<td style="text-align:left"><a href="https://huggingface.co/{m.id}" '
            f'target="_blank" style="color:#1677ff;text-decoration:none">{m.id}</a></td>'
            f"<td>{m.last_modified}</td><td>{m.downloads:,}</td>"
            f"<td>{m.likes}</td><td>{m.pipeline_tag or '-'}</td>"
            "</tr>"
        )
        md_rows.append(
            f"| [{m.id}](https://huggingface.co/{m.id}) | {m.last_modified} | "
            f"{m.downloads:,} | {m.likes} | {m.pipeline_tag or '-'} |"
        )

    ptr = []
    pmd_rows = [
        "| 日期 | 标题 | 作者 | 组织 | 点赞 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in papers:
        aff = p.organization or "-"
        ptr.append(
            "<tr>"
            f"<td>{p.published}</td>"
            f'<td style="text-align:left"><a href="{p.link}" target="_blank" '
            f'style="color:#1677ff;text-decoration:none">{p.title}</a></td>'
            f'<td style="text-align:left">{p.authors[:40]}</td>'
            f"<td>{aff[:20]}</td><td>{p.upvotes}</td>"
            "</tr>"
        )
        pmd_rows.append(
            f"| {p.published} | [{p.title}]({p.link}) | {p.authors[:40]} | "
            f"{aff[:20]} | {p.upvotes} |"
        )

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
<title>HuggingFace 监测 {name}({code}) {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>Hugging Face 监测：{name}（{code}）</h1>
<div class="meta">{as_of} · 数据来源：HF API（{_ENDPOINT}）· 模型组织：{org or '无'} · 论文检索：{company}</div>
<h2>最新模型（组织 {org or '无 HF 组织账号'}）</h2>
<div class="card"><table>
<tr><th style="text-align:left">模型</th><th>更新</th><th>下载</th><th>点赞</th><th>任务</th></tr>
{''.join(tr) if tr else '<tr><td colspan="5" style="text-align:center;color:#86909c">该组织无 HF 模型账号</td></tr>'}
</table></div>
<h2>HF 收录论文</h2>
<div class="card"><table>
<tr><th>日期</th><th style="text-align:left">标题</th><th style="text-align:left">作者</th><th>组织</th><th>点赞</th></tr>
{''.join(ptr) if ptr else '<tr><td colspan="5" style="text-align:center;color:#86909c">未检索到相关论文</td></tr>'}
</table></div>
<div class="footer">公开信息整理，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: HuggingFace 监测 {name}({code}) {as_of}
date: {as_of}
tags: [huggingface, 模型, 论文]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# Hugging Face 监测：{name}（{code}）

模型组织：{org or '无 HF 组织账号'} · 论文检索：{company}

## 最新模型

{chr(10).join(md_rows) if md_rows else "该组织无 HF 模型账号。"}

## HF 收录论文

{chr(10).join(pmd_rows) if pmd_rows else "未检索到相关论文。"}

> 公开信息整理，不构成投资建议。
"""
    return html, md
