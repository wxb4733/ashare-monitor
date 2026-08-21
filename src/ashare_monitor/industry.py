"""汽车行业景气数据（乘联会 CPCA 月度批发口径）。

数据源：akshare 乘联会接口（免费可及，行业权威口径）：
- car_market_total_cpca   : 月度总销量（万辆）
- car_market_fuel_cpca    : 分燃料/年度月度销量（新能源口径）
- car_market_man_rank_cpca: 厂商月度排名（比亚迪等自选股位置）

用途：行业景气先行指标（总量趋势/新能源渗透率/厂商份额）。
说明：中汽研（catarc.info）官方数据产品需授权；本模块采用乘联会（CPCA）
公开数据，口径为批发量。渗透率按 fuel/total 估算，如实标注口径。
不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class MonthlySeries:
    """月度序列：{月份: {年份: 值}}。"""
    name: str
    data: dict[str, dict[str, float]] = field(default_factory=dict)

    def latest(self) -> tuple[str, float] | None:
        """最新(月份, 值)。"""
        months = sorted(self.data.keys(),
                        key=lambda m: datetime.strptime(m, "%Y-%m"))
        if not months:
            return None
        m = months[-1]
        yrs = sorted(self.data[m].keys(), reverse=True)
        return m, self.data[m][yrs[0]]


@dataclass
class IndustryData:
    total: MonthlySeries          # 总销量
    new_energy: MonthlySeries     # 新能源销量
    penetration: dict[str, float] = field(default_factory=dict)  # {月份: 渗透率%}
    man_rank: list[dict] = field(default_factory=list)          # 厂商排名
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total.data, "new_energy": self.new_energy.data,
            "penetration": self.penetration, "man_rank": self.man_rank,
            "errors": self.errors,
        }


def _parse_monthly(df, name: str) -> MonthlySeries:
    """解析乘联会月度表（列=年份，行=月份）。"""
    import re

    ms = MonthlySeries(name)
    if df is None or df.empty:
        return ms
    for _, r in df.iterrows():
        month = str(r.iloc[0]).strip()
        for col in df.columns[1:]:
            year = re.sub(r"\D", "", str(col).strip())
            if year.isdigit() and len(year) == 4:
                try:
                    v = float(r[col])
                    if v == v and v > 0:  # 非 NaN
                        m = f"{year}-{int(''.join(filter(str.isdigit, month))):02d}"
                        ms.data.setdefault(m, {})[year] = v
                except (TypeError, ValueError):
                    continue
    return ms


def fetch_industry() -> IndustryData:
    """拉取乘联会行业数据。"""
    import akshare as ak

    ind = IndustryData(MonthlySeries("总销量"), MonthlySeries("新能源销量"))
    try:
        ind.total = _parse_monthly(ak.car_market_total_cpca(), "总销量")
    except Exception as exc:  # noqa: BLE001
        ind.errors.append(f"总销量：{exc}")
    try:
        ind.new_energy = _parse_monthly(ak.car_market_fuel_cpca(), "新能源")
    except Exception as exc:  # noqa: BLE001
        ind.errors.append(f"新能源：{exc}")
    # 渗透率（新能源/总销量，按同月同年）
    for m, years in ind.total.data.items():
        for y, tot in years.items():
            ne = ind.new_energy.data.get(m, {}).get(y)
            if ne and tot:
                ind.penetration[m] = round(ne / tot * 100, 1)
    # 厂商排名
    try:
        df = ak.car_market_man_rank_cpca()
        if df is not None and not df.empty:
            cols = list(df.columns)
            prev_col = next((c for c in cols if str(c).endswith("年")), None)
            cur_col = cols[-1]
            prev_col = cols[1] if len(cols) > 2 else None
            for i, r in df.iterrows():
                ind.man_rank.append({
                    "rank": i + 1,
                    "name": str(r[cols[0]]),
                    "cur": _num(r[cur_col]),
                    "prev": _num(r[prev_col]) if prev_col else None,
                    "chg": round((_num(r[cur_col]) / _num(r[prev_col]) - 1) * 100, 1)
                    if prev_col and _num(r[prev_col]) else None,
                })
    except Exception as exc:  # noqa: BLE001
        ind.errors.append(f"厂商排名：{exc}")
    return ind


def _num(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def build_industry_report(ind: IndustryData,
                          as_of: str | None = None) -> tuple[str, str]:
    """生成行业数据报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    tot_latest = ind.total.latest()
    ne_latest = ind.new_energy.latest()
    pen = sorted(ind.penetration.items(),
                 key=lambda kv: datetime.strptime(kv[0], "%Y-%m"))[-1] \
        if ind.penetration else None

    # 总销量近 6 期
    months = sorted(ind.total.data.keys(),
                    key=lambda m: datetime.strptime(m, "%Y-%m"))[-6:]
    tr = []
    md_rows = ["| 月份 | 总销量(万辆) | 新能源(万辆) | 渗透率 |",
               "| --- | --- | --- | --- |"]
    for m in months:
        tot = max(ind.total.data[m].values()) if ind.total.data.get(m) else None
        ne = max(ind.new_energy.data[m].values()) if ind.new_energy.data.get(m) else None
        p = ind.penetration.get(m)
        tot_c = f"<td>{tot:.1f}</td>" if tot is not None else "<td>-</td>"
        ne_c = f"<td>{ne:.1f}</td>" if ne is not None else "<td>-</td>"
        p_c = f"<td>{p:.1f}%</td>" if p is not None else "<td>-</td>"
        tr.append(f"<tr><td>{m}</td>{tot_c}{ne_c}{p_c}</tr>")
        md_rows.append(
            f"| {m} | {tot:.1f}" if tot is not None else f"| {m} | -"
            + (f" | {ne:.1f}" if ne is not None else " | -")
            + (f" | {p:.1f}%" if p is not None else " | - |")
        )

    # 厂商排名
    rtr = []
    rmd = ["| 排名 | 厂商 | 最新(万辆) | 上年同期 | 同比 |",
           "| --- | --- | --- | --- | --- |"]
    for x in ind.man_rank[:10]:
        chg = f"{x['chg']:+.1f}%" if x["chg"] is not None else "-"
        color = "#e02e24" if (x["chg"] or 0) >= 0 else "#00a870"
        cur_c = (f"<td>{x['cur']:.1f}</td>"
                 if x["cur"] is not None else "<td>-</td>")
        prev_c = (f"<td>{x['prev']:.1f}</td>"
                  if x["prev"] is not None else "<td>-</td>")
        chg_c = f'<td><span style="color:{color}">{chg}</span></td>'
        rtr.append(f"<tr><td>{x['rank']}</td><td>{x['name']}</td>"
                   f"{cur_c}{prev_c}{chg_c}</tr>")
        cur_s = f"{x['cur']:.1f}" if x["cur"] is not None else "-"
        prev_s = f"{x['prev']:.1f}" if x["prev"] is not None else "-"
        rmd.append(f"| {x['rank']} | {x['name']} | {cur_s} | {prev_s} | {chg} |")

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
    tot_cell = (f"{tot_latest[1]:.1f} 万辆（{tot_latest[0]}）"
                if tot_latest else "-")
    ne_cell = (f"{ne_latest[1]:.1f} 万辆（{ne_latest[0]}）"
               if ne_latest else "-")
    pen_cell = f"{pen[1]:.1f}%（{pen[0]}）" if pen else "-"
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>汽车行业数据 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>汽车行业景气数据（乘联会 CPCA）</h1>
<div class="meta">{as_of} · 最新：总销量 {tot_cell} · 新能源 {ne_cell} · 渗透率 {pen_cell} · 口径：批发量</div>
<h2>月度趋势（近 6 期）</h2>
<div class="card"><table>
<tr><th>月份</th><th>总销量(万辆)</th><th>新能源(万辆)</th><th>渗透率</th></tr>
{''.join(tr) if tr else '<tr><td colspan="4" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<h2>厂商排名（TOP10）</h2>
<div class="card"><table>
<tr><th>排名</th><th>厂商</th><th>最新(万辆)</th><th>上年同期</th><th>同比</th></tr>
{''.join(rtr) if rtr else '<tr><td colspan="5" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<div class="footer">数据来源：乘联会（CPCA）公开批发数据；渗透率按新能源/总销量估算。
中汽研官方数据产品需授权。不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 汽车行业数据 {as_of}
date: {as_of}
tags: [行业, 乘联会, 景气]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 汽车行业景气数据（乘联会 CPCA）

最新：总销量 {tot_cell} · 新能源 {ne_cell} · 渗透率 {pen_cell}

## 月度趋势

{chr(10).join(md_rows) if md_rows else "无数据。"}

## 厂商排名（TOP10）

{chr(10).join(rmd) if rmd else "无数据。"}

> 数据来源：乘联会（CPCA）公开批发数据，不构成投资建议。
"""
    return html, md
