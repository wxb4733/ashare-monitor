"""估值分位监控：PE(TTM)/PB 历史百分位。

数据源：东财估值分析 RPT_VALUEANALYSIS_DET（按代码历史序列直连）。
当前 PE/PB 与其近 N 年历史百分位：百分位 <20% → 低估区间，>80% → 高估区间。
字段：TRADE_DATE/CLOSE_PRICE/PE_TTM/PB_MRQ。

说明：估值分位为规则化统计参考，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

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
class Valuation:
    code: str
    name: str
    date: str
    close: float | None
    pe_ttm: float | None
    pb_mrq: float | None
    pe_pct: float | None      # PE 历史百分位 %
    pb_pct: float | None

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "date": self.date,
            "close": self.close, "pe_ttm": self.pe_ttm, "pb_mrq": self.pb_mrq,
            "pe_pct": self.pe_pct, "pb_pct": self.pb_pct,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_valuation(code: str, years: int = 5,
                    name: str = "") -> Valuation | None:
    """查询代码估值与历史百分位（近 years 年，约 250*years 个交易日）。"""
    resp = requests.get(
        _API,
        params={
            "reportName": "RPT_VALUEANALYSIS_DET",
            "columns": "ALL",
            "pageSize": 250 * years + 10, "pageNumber": 1,
            "filter": f'(SECURITY_CODE="{code[-6:]}")',
            "sortColumns": "TRADE_DATE", "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        },
        headers=_HEADERS, timeout=15,
    )
    resp.raise_for_status()
    rows = (resp.json().get("result") or {}).get("data") or []
    if not rows:
        return None
    latest = rows[0]
    pes = sorted(_f(r.get("PE_TTM")) for r in rows if _f(r.get("PE_TTM")) is not None)
    pbs = sorted(_f(r.get("PB_MRQ")) for r in rows if _f(r.get("PB_MRQ")) is not None)

    def _pct(v: float | None, series: list[float]) -> float | None:
        if v is None or not series:
            return None
        below = sum(1 for x in series if x <= v)
        return round(below / len(series) * 100, 1)

    pe, pb = _f(latest.get("PE_TTM")), _f(latest.get("PB_MRQ"))
    return Valuation(
        code=code, name=name, date=str(latest.get("TRADE_DATE") or "")[:10],
        close=_f(latest.get("CLOSE_PRICE")),
        pe_ttm=pe, pb_mrq=pb,
        pe_pct=_pct(pe, pes), pb_pct=_pct(pb, pbs),
    )


def scan_watchlist_valuation(cfg, years: int = 5) -> list[Valuation]:
    """扫描自选股估值分位（A 股）。"""
    vals = []
    for it in cfg.watchlist:
        if str(it.get("market", "ashare")) != "ashare":
            continue
        c = str(it["code"])
        name = str(it.get("name", c))
        try:
            v = fetch_valuation(c, years=years, name=name)
            if v:
                vals.append(v)
        except Exception as exc:  # noqa: BLE001
            logger.warning("估值 %s 失败: %s", c, exc)
    return vals


def _zone(v: float | None) -> str:
    if v is None:
        return "-"
    return "低估" if v < 20 else ("高估" if v > 80 else "中性")


def build_valuation_report(rows: list[Valuation], years: int,
                           as_of: str | None = None) -> tuple[str, str]:
    """生成估值分位报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _fmt(v, nd: int = 2) -> str:
        return f"{v:.{nd}f}" if v is not None else "-"

    tr = []
    md_rows = [
        "| 标的 | 日期 | 收盘 | PE(TTM) | PE分位 | PB | PB分位 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for x in rows:
        pe_z, pb_z = _zone(x.pe_pct), _zone(x.pb_pct)

        def _cell(v, z):
            color = "#00a870" if z == "低估" else ("#e02e24" if z == "高估" else "")
            return (f'<span style="color:{color}">{_fmt(v)} ({z})</span>'
                    if color else f"{_fmt(v)} ({z})")
        tr.append(
            "<tr>"
            f"<td>{x.name}({x.code})</td><td>{x.date}</td>"
            f"<td>{_fmt(x.close)}</td>"
            f"<td>{_cell(x.pe_ttm, pe_z)}</td>"
            f"<td>{_fmt(x.pe_pct, 1)}%</td>"
            f"<td>{_cell(x.pb_mrq, pb_z)}</td>"
            f"<td>{_fmt(x.pb_pct, 1)}%</td>"
            "</tr>"
        )
        md_rows.append(
            f"| {x.name}({x.code}) | {x.date} | {_fmt(x.close)} | "
            f"{_fmt(x.pe_ttm)} ({pe_z}) | {_fmt(x.pe_pct, 1)}% | "
            f"{_fmt(x.pb_mrq)} ({pb_z}) | {_fmt(x.pb_pct, 1)}% |"
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
<title>估值分位 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>估值分位监控（近 {years} 年）</h1>
<div class="meta">{as_of} · 数据来源：东财估值分析 · 分位 &lt;20% 低估(绿) / &gt;80% 高估(红)</div>
<div class="card"><table>
<tr><th>标的</th><th>日期</th><th>收盘</th><th>PE(TTM)</th><th>PE分位</th><th>PB</th><th>PB分位</th></tr>
{''.join(tr) if tr else '<tr><td colspan="7" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<div class="footer">估值分位为规则化统计参考，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 估值分位 {as_of}
date: {as_of}
tags: [估值, PE, PB]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 估值分位监控（近 {years} 年）

{chr(10).join(md_rows) if md_rows else "无数据。"}

> 估值分位为规则化统计参考，不构成投资建议。
"""
    return html, md
