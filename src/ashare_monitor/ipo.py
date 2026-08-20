"""IPO 公司分析模块。

数据源：东方财富数据中心新股申购/上市报表 RPTA_APP_IPOAPPLY（直连，无需鉴权）。

提供：
- 近期新股列表（申购/上市日历，按申购日倒序）
- 单只新股详情（发行价、募资、行业、主营、保荐机构等）
- 规则化分析：发行阶段、发行 PE vs 行业 PE、募资完成度、上市表现（破发提示）

仅支持 A 股。解析函数与网络解耦，便于测试。

声明：IPO 分析为投资参考信息，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import requests

from .signals import DISCLAIMER

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}

_IPO_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"


@dataclass
class IPORecord:
    code: str
    name: str
    market: str                       # 交易所
    industry: str                     # 行业
    apply_date: str                   # 申购日 YYYY-MM-DD（无则空）
    listing_date: str                 # 上市日（无则空）
    issue_price: float | None         # 发行价
    issue_pe: float | None            # 发行市盈率（发行价/每股收益 估算，缺失为 None）
    industry_pe: float | None         # 行业市盈率
    raise_funds: float | None         # 实际募资（亿元）
    plan_funds: float | None          # 计划募资（亿元）
    issue_num: float | None           # 发行量（万股）
    main_business: str                # 主营业务
    underwriter: str                  # 保荐机构
    newest_price: float | None        # 上市后最新价（未上市为 None）

    @property
    def pe_ratio(self) -> float | None:
        """发行 PE / 行业 PE。"""
        if self.issue_pe is not None and self.industry_pe:
            return self.issue_pe / self.industry_pe
        return None

    def stage(self, now: datetime | None = None) -> str:
        """发行阶段：待定价 / 待申购 / 待上市 / 已上市。"""
        now = now or datetime.now()
        today = now.strftime("%Y-%m-%d")
        if self.newest_price is not None or (self.listing_date and self.listing_date <= today):
            return "已上市"
        if self.issue_price is None:
            return "待定价"
        if self.apply_date and self.apply_date > today:
            return "待申购"
        return "待上市"


def fetch_ipo_list(limit: int = 50) -> list[IPORecord]:
    """拉取近期新股列表（按申购日倒序）。"""
    resp = requests.get(
        _IPO_API,
        params={
            "reportName": "RPTA_APP_IPOAPPLY",
            "columns": "ALL",
            "pageSize": limit, "pageNumber": 1,
            "sortColumns": "APPLY_DATE", "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        },
        headers=_HEADERS, timeout=12,
    )
    resp.raise_for_status()
    data = (resp.json().get("result") or {}).get("data") or []
    items = parse_ipo_list(data)
    if not items:
        raise RuntimeError("未获取到新股数据")
    return items


def parse_ipo_list(data: list[dict]) -> list[IPORecord]:
    """解析东财新股报表 JSON（独立出来便于测试）。"""
    result = []
    for it in data:
        issue_price = _to_float(it.get("ISSUE_PRICE"))
        # 发行市盈率：优先发行价/每股收益
        eps = _to_float(it.get("PER_SHARES_INCOME"))
        issue_pe = (
            issue_price / eps if issue_price is not None and eps else
            _to_float(it.get("PREDICT_ISSUE_PE"))
        )
        result.append(IPORecord(
            code=str(it.get("SECURITY_CODE", "")),
            name=str(it.get("SECURITY_NAME_ABBR") or it.get("SECURITY_NAME", "")),
            market=str(it.get("TRADE_MARKET") or ""),
            industry=str(it.get("INDUSTRY_NAME") or ""),
            apply_date=str(it.get("APPLY_DATE") or "")[:10],
            listing_date=str(it.get("LISTING_DATE") or "")[:10],
            issue_price=issue_price,
            issue_pe=round(issue_pe, 2) if issue_pe is not None else None,
            industry_pe=_to_float(it.get("INDUSTRY_PE_NEW") or it.get("INDUSTRY_PE")),
            raise_funds=_to_float(it.get("TOTAL_RAISE_FUNDS")),
            plan_funds=_to_float(it.get("PREDICT_RAISE_FUNDS")),
            issue_num=_to_float(it.get("TOTAL_ISSUE_NUM")),
            main_business=str(it.get("MAIN_BUSINESS") or ""),
            underwriter=str(it.get("UNDERWRITER_ORG") or ""),
            newest_price=_to_float(it.get("NEWEST_PRICE")),
        ))
    return result


def find_ipo(items: list[IPORecord], keyword: str) -> IPORecord | None:
    """按代码精确或名称包含查找。"""
    kw = keyword.strip()
    for it in items:
        if it.code == kw or kw in it.name:
            return it
    return None


def analyze_ipo(rec: IPORecord, now: datetime | None = None) -> list[str]:
    """规则化 IPO 分析（不构成投资建议）。"""
    lines = []
    stage = rec.stage(now)

    # 1. 发行阶段
    if stage == "待定价":
        lines.append("尚未定价：发行价/市盈率待公布，可关注后续询价结果")
    elif stage == "待申购":
        lines.append(f"待申购：网上申购日为 {rec.apply_date}，可提前了解发行资料")
    elif stage == "待上市":
        lines.append(f"待上市：已定价发行价 {rec.issue_price:.2f} 元，"
                     + (f"上市日 {rec.listing_date}" if rec.listing_date else "上市日待定"))
    else:
        if rec.newest_price is not None and rec.issue_price:
            change = (rec.newest_price / rec.issue_price - 1) * 100
            if change < 0:
                lines.append(
                    f"已上市且现价 {rec.newest_price:.2f} 元低于发行价 {rec.issue_price:.2f} 元"
                    f"（{change:+.1f}%），已破发，注意风险"
                )
            else:
                lines.append(
                    f"已上市：现价 {rec.newest_price:.2f} 元较发行价 {rec.issue_price:.2f} 元"
                    f"上涨 {change:+.1f}%"
                )

    # 2. 发行 PE vs 行业 PE
    ratio = rec.pe_ratio
    if ratio is not None and rec.industry_pe is not None:
        if ratio >= 1.5:
            lines.append(
                f"发行 PE {rec.issue_pe:.1f} 显著高于行业 {rec.industry_pe:.1f}"
                f"（{ratio:.2f} 倍），估值偏贵"
            )
        elif ratio <= 0.8:
            lines.append(
                f"发行 PE {rec.issue_pe:.1f} 低于行业 {rec.industry_pe:.1f}"
                f"（{ratio:.2f} 倍），估值相对便宜"
            )
        else:
            lines.append(
                f"发行 PE {rec.issue_pe:.1f} 与行业 {rec.industry_pe:.1f} 基本持平"
                f"（{ratio:.2f} 倍）"
            )
    elif rec.issue_pe is not None:
        lines.append(f"发行 PE {rec.issue_pe:.1f}（暂无行业对比）")

    # 3. 募资完成度
    if rec.raise_funds is not None and rec.plan_funds:
        ratio_f = rec.raise_funds / rec.plan_funds * 100
        if ratio_f >= 105:
            lines.append(f"实际募资 {rec.raise_funds:.2f} 亿，超募 {ratio_f - 100:.0f}%（市场认购踊跃）")
        elif ratio_f <= 95:
            lines.append(f"实际募资 {rec.raise_funds:.2f} 亿，缩募（仅计划 {rec.plan_funds:.0f} 亿的 {ratio_f:.0f}%）")
        else:
            lines.append(f"募资 {rec.raise_funds:.2f} 亿，基本达成计划（{rec.plan_funds:.0f} 亿）")

    # 4. 基本信息摘要
    if rec.main_business:
        biz = rec.main_business if len(rec.main_business) <= 60 else rec.main_business[:57] + "…"
        lines.append(f"主营：{biz}")
    if rec.underwriter:
        lines.append(f"保荐机构：{rec.underwriter}")

    return lines


def _to_float(v) -> float | None:
    try:
        if v is None or v == "" or v == "--":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- IPO 分析报告 ----------

_IPO_CSS = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1080px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 24px 0 8px; }
.meta { color: #86909c; font-size: 12px; margin-bottom: 16px; }
.card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
th { background: #fafafa; color: #666; font-weight: 600; }
th:first-child, td:first-child { text-align: left; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; background: #f0f0f0; color: #666; }
.up { color: #e02e24; } .down { color: #00a870; }
.break { color: #e02e24; font-weight: 600; }
.analysis li { margin: 4px 0; font-size: 13px; }
.analysis .tag { margin-right: 6px; }
.footer { color: #86909c; font-size: 12px; text-align: center; padding: 16px 0 8px; }
"""


def _stage_cn(stage: str) -> tuple[str, str]:
    """状态中文名 + 颜色。"""
    return {
        "待申购": ("待申购", "#1677ff"),
        "待定价": ("待定价", "#faad14"),
        "待上市": ("待上市", "#722ed1"),
        "已上市": ("已上市", "#52c41a"),
    }.get(stage, (stage, ""))


def build_ipo_report(
    items: list[IPORecord],
    as_of: str | None = None,
) -> tuple[str, str]:
    """生成 IPO 分析报告（HTML, Markdown 两版）。仅含最近 N 条，按申购日倒序。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    today = datetime.strptime(as_of, "%Y-%m-%d")

    def _fmt(v: float | None, nd: int = 2, suffix: str = "") -> str:
        return f"{v:.{nd}f}{suffix}" if v is not None else "-"

    # ---- 表格行 ----
    table_rows = []
    md_rows = []
    focus: list[IPORecord] = []        # 待申购/待上市（重点分析）
    breaks: list[tuple[IPORecord, float]] = []  # 破发
    for rec in items:
        stage = rec.stage(today)
        st_cn, st_color = _stage_cn(stage)
        mkt = rec.market.replace("证券交易所", "")
        table_rows.append(
            "<tr>"
            f"<td>{rec.code}</td><td>{rec.name}</td><td>{mkt}</td>"
            f"<td>{rec.industry or '-'}</td>"
            f"<td>{rec.apply_date or '-'}</td><td>{rec.listing_date or '-'}</td>"
            f"<td>{_fmt(rec.issue_price)}</td>"
            f"<td>{_fmt(rec.industry_pe, 1)}</td>"
            f"<td>{_fmt(rec.raise_funds)}</td>"
            f'<td><span class="tag" style="color:{st_color}">{st_cn}</span></td>'
            "</tr>"
        )
        md_rows.append(
            f"| {rec.code} | {rec.name} | {mkt} | {rec.industry or '-'} | "
            f"{rec.apply_date or '-'} | {rec.listing_date or '-'} | "
            f"{_fmt(rec.issue_price)} | {_fmt(rec.industry_pe, 1)} | "
            f"{_fmt(rec.raise_funds)} | {st_cn} |"
        )
        if stage in ("待申购", "待上市"):
            focus.append(rec)
        if stage == "已上市" and rec.newest_price is not None and rec.issue_price:
            chg = (rec.newest_price / rec.issue_price - 1) * 100
            if chg < 0:
                breaks.append((rec, chg))

    # ---- 重点新股分析（HTML）----
    focus_html = ""
    if focus:
        blocks = [f"<h2>重点新股分析（{len(focus)} 只待申购 / 待上市）</h2>"]
        for rec in sorted(focus, key=lambda r: r.apply_date):
            lines = analyze_ipo(rec, today)
            st_cn, _ = _stage_cn(rec.stage(today))
            lis = "".join(f"<li>{ln}</li>" for ln in lines)
            blocks.append(
                f"<div class=\"card\"><h2 style=\"margin-top:0\">{rec.name}"
                f"({rec.code}) <span class=\"tag\">{st_cn}</span></h2>"
                f"<ul class=\"analysis\">{lis}</ul></div>"
            )
        focus_html = "".join(blocks)

    # ---- 破发提示（HTML）----
    break_html = ""
    if breaks:
        rows = "".join(
            f"<tr><td>{r[0].code}</td><td>{r[0].name}</td>"
            f"<td>{_fmt(r[0].issue_price)}</td><td>{_fmt(r[0].newest_price)}</td>"
            f'<td class="break">{r[1]:+.1f}%</td></tr>'
            for r in sorted(breaks, key=lambda x: x[1])
        )
        break_html = (
            "<h2>破发提示（已上市且现价低于发行价）</h2>"
            '<div class="card"><table>'
            "<tr><th>代码</th><th>名称</th><th>发行价</th><th>现价</th><th>较发行价</th></tr>"
            f"{rows}</table></div>"
        )

    # ---- 重点新股分析（Markdown）----
    focus_md = ""
    if focus:
        lines = ["## 重点新股分析", ""]
        for rec in sorted(focus, key=lambda r: r.apply_date):
            st_cn, _ = _stage_cn(rec.stage(today))
            lines.append(f"### {rec.name}({rec.code}) · {st_cn}")
            for ln in analyze_ipo(rec, today):
                lines.append(f"- {ln}")
            lines.append("")
        focus_md = "\n".join(lines)

    # ---- 破发提示（Markdown）----
    break_md = ""
    if breaks:
        lines = ["## 破发提示", "", "| 代码 | 名称 | 发行价 | 现价 | 较发行价 |", "| --- | --- | --- | --- | --- |"]
        for rec, chg in sorted(breaks, key=lambda x: x[1]):
            lines.append(
                f"| {rec.code} | {rec.name} | {_fmt(rec.issue_price)} | "
                f"{_fmt(rec.newest_price)} | {chg:+.1f}% |"
            )
        break_md = "\n".join(lines) + "\n"

    table_html = "".join(table_rows)
    table_md = (
        "| 代码 | 名称 | 交易所 | 行业 | 申购日 | 上市日 | 发行价 | 行业PE | 募资(亿) | 状态 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        + "\n".join(md_rows)
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>IPO 分析报告 {as_of}</title>
<style>{_IPO_CSS}</style>
</head>
<body>
<div class="container">
<h1>IPO 分析报告</h1>
<div class="meta">{as_of} · 生成于 {datetime.now():%Y-%m-%d %H:%M:%S} · 数据来源：东方财富公开数据接口</div>
<h2>近期新股日历（共 {len(items)} 只，按申购日倒序）</h2>
<div class="card"><table>
<tr><th>代码</th><th>名称</th><th>交易所</th><th>行业</th><th>申购日</th><th>上市日</th><th>发行价</th><th>行业PE</th><th>募资(亿)</th><th>状态</th></tr>
{table_html}
</table></div>
{focus_html}
{break_html}
<div class="footer">{DISCLAIMER}</div>
</div>
</body>
</html>"""

    md = f"""---
title: IPO分析报告 {as_of}
date: {as_of}
tags: [IPO, A股]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# IPO 分析报告 {as_of}

## 近期新股日历（共 {len(items)} 只，按申购日倒序）

{table_md}

{focus_md}
{break_md}
> {DISCLAIMER}
"""
    return html, md
