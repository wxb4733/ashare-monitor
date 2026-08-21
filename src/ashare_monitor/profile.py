"""公司档案：工商信息 + 股权结构。

数据源：
- 工商概况：巨潮资讯 stock_profile_cninfo（公司全称/法人/注册资本/成立上市日期/
  行业/注册地址/主营/经营范围等）
- 股权结构：东财 F10 十大股东（复用 holders.fetch_top10）；实控人为规则化推断
  （十大股东中持股最多的自然人），如实标注"推断"

说明：实控人/股权穿透完整数据需企查查/天眼查（连接器）；本模块为公开源可及的
规则化呈现，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class CompanyProfile:
    code: str
    market: str
    name: str = ""
    full_name: str = ""
    en_name: str = ""
    legal_person: str = ""       # 法人代表
    reg_capital: float | None = None   # 注册资金（万元）
    founded: str = ""            # 成立日期
    listed: str = ""             # 上市日期
    industry: str = ""           # 所属行业
    market_board: str = ""       # 所属市场/板块
    reg_address: str = ""
    office_address: str = ""
    website: str = ""
    phone: str = ""
    email: str = ""
    main_biz: str = ""           # 主营业务
    biz_scope: str = ""          # 经营范围
    hk_code: str = ""            # H 股代码（如有）
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def fetch_profile(code: str, market: str = "ashare") -> CompanyProfile:
    """获取公司工商概况（巨潮）。港股暂不支持返回空档案。"""
    p = CompanyProfile(code=code, market=market)
    if market != "ashare":
        p.errors.append("港股工商概况暂不支持（数据源为巨潮 A 股）")
        return p
    try:
        import akshare as ak

        df = ak.stock_profile_cninfo(symbol=code)
        if df is None or df.empty:
            p.errors.append("巨潮无该公司档案")
            return p
        r = df.iloc[0]

        def _s(k: str) -> str:
            v = r.get(k)
            return "" if v is None or str(v) in ("nan", "None") else str(v).strip()

        p.name = _s("A股简称") or code
        p.full_name = _s("公司名称")
        p.en_name = _s("英文名称")
        p.legal_person = _s("法人代表")
        p.reg_capital = _f(_s("注册资金"))
        p.founded = _s("成立日期")[:10]
        p.listed = _s("上市日期")[:10]
        p.industry = _s("所属行业")
        p.market_board = _s("所属市场")
        p.reg_address = _s("注册地址")
        p.office_address = _s("办公地址")
        p.website = _s("官方网站")
        p.phone = _s("联系电话")
        p.email = _s("电子邮箱")
        p.main_biz = _s("主营业务")
        p.biz_scope = _s("经营范围")
        p.hk_code = _s("H股代码")
    except Exception as exc:  # noqa: BLE001
        logger.warning("工商概况获取失败: %s", exc)
        p.errors.append(f"工商概况获取失败：{exc}")
    return p


def _f(v: str) -> float | None:
    try:
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


def infer_controller(top_holders: list) -> str:
    """规则化推断实控人：十大股东中持股最多的自然人。

    :param top_holders: holders.TopHolder 列表
    :return: "姓名(占比%)" 或 ""
    """
    persons = [h for h in top_holders if h.name and len(h.name) <= 4
               and not any(k in h.name for k in ("公司", "有限", "银行", "基金",
                                                 "HKSCC", "NOMINEES", "信托",
                                                 "合伙", "投资"))]
    if not persons:
        return ""
    p = max(persons, key=lambda h: h.ratio or 0)
    return f"{p.name}({p.ratio:.2f}%)" if p.ratio is not None else p.name


def build_profile_report(
    p: CompanyProfile, top_holders: list,
    report_date: str, as_of: str | None = None,
) -> tuple[str, str]:
    """生成公司档案报告（HTML, Markdown）。"""
    from .holders import TopHolder

    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _cap(v: float | None) -> str:
        if v is None:
            return "-"
        return f"{v / 10000:.2f} 亿元" if v >= 10000 else f"{v:.0f} 万元"

    items = [
        ("公司全称", p.full_name), ("英文名称", p.en_name),
        ("法人代表", p.legal_person), ("注册资金", _cap(p.reg_capital)),
        ("成立日期", p.founded), ("上市日期", p.listed),
        ("所属行业", p.industry), ("所属市场", p.market_board),
        ("H股代码", p.hk_code or "-"), ("注册地址", p.reg_address),
        ("办公地址", p.office_address), ("官网", p.website),
        ("电话", p.phone), ("邮箱", p.email),
    ]
    rows = "".join(
        f"<tr><th style=\"text-align:left;width:120px\">{k}</th>"
        f"<td style=\"text-align:left\">{v or '-'}</td></tr>"
        for k, v in items
    )
    md_rows = "\n".join(f"- **{k}**：{v or '-'}" for k, v in items)

    # 股权结构
    total_ratio = sum(h.ratio for h in top_holders if h.ratio is not None)
    controller = infer_controller(top_holders)
    tr = []
    htr = []
    for h in top_holders:
        chg = h.change + (f" {h.change_ratio:+.1f}%" if h.change_ratio is not None else "")
        tr.append(
            "<tr>"
            f"<td>{h.rank}</td><td style=\"text-align:left\">{h.name}</td>"
            f"<td>{h.share_type}</td><td>{h.ratio:.2f}%</td>"
            f"<td>{chg}</td></tr>"
        )
        htr.append(f"| {h.rank} | {h.name} | {h.share_type} | "
                   f"{h.ratio:.2f}% | {chg} |")

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
<title>公司档案 {p.name}({p.code}) {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>公司档案：{p.name}（{p.code}）</h1>
<div class="meta">{as_of} · 工商来源：巨潮资讯 · 股权来源：东财 F10（报告期 {report_date}）</div>
<h2>工商信息</h2>
<div class="card"><table>{rows}</table></div>
<h2>股权结构（十大股东合计 {total_ratio:.1f}%）</h2>
<div class="card"><p style="font-size:13px;color:#1f2329">
疑似实际控制人（推断：持股最多的自然人）：<b>{controller or '未识别'}</b></p>
<table>
<tr><th>名次</th><th style="text-align:left">股东</th><th>类型</th><th>占比</th><th>变动</th></tr>
{''.join(tr) if tr else '<tr><td colspan="5" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<div class="footer">实控人为规则化推断，完整股权穿透需企业数据库。公开信息整理，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 公司档案 {p.name}({p.code}) {as_of}
date: {as_of}
tags: [工商, 股权]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 公司档案：{p.name}（{p.code}）

疑似实际控制人（推断）：**{controller or '未识别'}**

## 工商信息

{md_rows}

## 股权结构（十大股东合计 {total_ratio:.1f}%）

| 名次 | 股东 | 类型 | 占比 | 变动 |
| --- | --- | --- | --- | --- |
{chr(10).join(htr) if htr else "无数据。"}

> 实控人为规则化推断，不构成投资建议。
"""
    return html, md
