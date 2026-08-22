"""股息率榜单时长分析：全市场各年股息率榜 → 上榜年数排名。

数据源：东财分红送配报表（stock_fhps_em，按年全市场），字段"现金分红-股息率"
为小数形式（0.026 = 2.61%，已实测验证口径）。
榜单口径：每年股息率 ≥ min_yield（默认 3%）或按排名 top_k。

算法：逐年拉取 → 每年筛上榜 → 按代码累计上榜年数 → 降序。
注意：早期年份（<2010）东财报表覆盖不全或接口无数据，榜单时长为
"数据可得期内"统计，如实标注年份区间。
不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RankStat:
    code: str
    name: str
    years_on_list: int          # 上榜年数
    total_years: int            # 数据可得年数
    years_detail: list[int]     # 上榜年份
    best_yield: float | None    # 最高年度股息率 %
    latest_yield: float | None
    cum_dps: float | None = None    # 累计每股派息（元）
    price: float | None = None      # 当前价（本地 K 线最新）
    cum_yield: float | None = None  # 累计股息率 %（累计派息/现价）

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name,
            "years_on_list": self.years_on_list,
            "total_years": self.total_years,
            "years_detail": self.years_detail,
            "best_yield": self.best_yield,
            "latest_yield": self.latest_yield,
            "cum_dps": self.cum_dps, "price": self.price,
            "cum_yield": self.cum_yield,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", "", "none"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch_close_price(code: str) -> float | None:
    """东财 datacenter 单票最新收盘价。"""
    import requests

    try:
        d = requests.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params={
                "reportName": "RPT_VALUEANALYSIS_DET",
                "columns": "ALL", "pageSize": 1, "pageNumber": 1,
                "filter": f'(SECURITY_CODE="{code}")',
                "sortColumns": "TRADE_DATE", "sortTypes": -1,
                "source": "WEB", "client": "WEB",
            },
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": "https://data.eastmoney.com/"},
            timeout=10,
        ).json()
        rows = (d.get("result") or {}).get("data") or []
        if rows:
            return _f(rows[0].get("CLOSE_PRICE"))
    except Exception:  # noqa: BLE001
        pass
    return None


def _fetch_year(date: str, retries: int = 2):
    """拉单年报表（带重试，东财域偶发失败）。"""
    import akshare as ak

    last = None
    for _ in range(retries + 1):
        try:
            return ak.stock_fhps_em(date=date)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5)
    raise RuntimeError(f"年度报表 {date} 拉取失败: {last}")


def rank_dividend_persistence(years: list[int] | None = None,
                              min_yield: float = 3.0,
                              top_k: int | None = 50) -> list[RankStat]:
    """统计各股在股息率榜单（≥min_yield%）的上榜年数。

    :param years: 统计年份（默认 2010~今年，数据可得期）
    :param min_yield: 上榜阈值 %（默认 3）
    :param top_k: 或按每年排名取前 top_k（None 则不启用）
    """
    years = years or list(range(2010, datetime.now().year + 1))
    yearly_on: dict[str, set[int]] = {}
    yearly_best: dict[str, float] = {}
    yearly_latest: dict[str, float] = {}
    cum_dps: dict[str, float] = {}   # 累计每股派息
    valid_years = 0

    for year in years:
        try:
            df = _fetch_year(f"{year}1231")
        except Exception as exc:  # noqa: BLE001
            logger.warning("跳过 %s: %s", year, exc)
            continue
        if df is None or df.empty:
            continue
        valid_years += 1
        dy_col = next((c for c in df.columns if "股息率" in c), None)
        if not dy_col:
            continue
        code_col, name_col = df.columns[0], df.columns[1]
        dps_col = next((c for c in df.columns if "现金分红比例" in c
                        or "现金分红-现金分红" in c), None)
        rows = []
        for _, r in df.iterrows():
            dy = _f(r.get(dy_col))
            if dy is None:
                continue
            dy_pct = dy * 100  # 小数 → %
            code = str(r.get(code_col) or "")
            name = str(r.get(name_col) or "")
            dps10 = _f(r.get(dps_col)) if dps_col else None
            dps = dps10 / 10.0 if dps10 is not None else None
            rows.append((code, name, dy_pct, dps))
        if not rows:
            continue
        if top_k:
            rows.sort(key=lambda x: x[2], reverse=True)
            on_list = rows[:top_k]
        else:
            on_list = [x for x in rows if x[2] >= min_yield]
        for code, name, dy_pct, dps in on_list:
            yearly_on.setdefault(code, set()).add(year)
            yearly_best[code] = max(yearly_best.get(code, 0.0), dy_pct)
            yearly_latest[code] = dy_pct
            name_by_code.setdefault(code, name)
            if dps is not None:
                cum_dps[code] = cum_dps.get(code, 0.0) + dps

    # 当前价：datacenter 单票（逐只）→ 降级本地 K 线
    price_cache: dict[str, float] = {}
    for code in yearly_on:
        got = _fetch_close_price(code)
        if got is None:
            try:
                from .storage import load_klines

                rows = load_klines(code, "ashare")
                if rows:
                    got = float(rows[-1]["close"])
            except Exception:  # noqa: BLE001
                got = None
        if got:
            price_cache[code] = got

    stats = []
    for code, yset in yearly_on.items():
        dps = cum_dps.get(code)
        price = price_cache.get(code)
        cy = (dps / price * 100) if dps is not None and price else None
        stats.append(RankStat(
            code=code, name=name_by_code.get(code, code),
            years_on_list=len(yset), total_years=valid_years,
            years_detail=sorted(yset),
            best_yield=yearly_best.get(code),
            latest_yield=yearly_latest.get(code),
            cum_dps=dps, price=price, cum_yield=cy,
        ))
    stats.sort(key=lambda x: (-x.years_on_list, -(x.best_yield or 0)))
    return stats


# 代码→名称缓存（首年抓取时记录）
name_by_code: dict[str, str] = {}


def _fill_names(stats: list[RankStat]) -> None:
    for s in stats:
        if s.name == s.code:
            s.name = name_by_code.get(s.code, s.code)


def build_rank_report(stats: list[RankStat], years_range: tuple[int, int],
                      min_yield: float, top_k: int | None,
                      as_of: str | None = None) -> tuple[str, str]:
    """生成榜单时长报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    rule = (f"每年 TOP {top_k}" if top_k
            else f"每年股息率 ≥ {min_yield}%")

    tr = []
    md_rows = [
        "| 代码 | 名称 | 上榜年数 | 数据年数 | 上榜年份 | 最高股息率 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, s in enumerate(stats[:30], 1):
        years_s = "、".join(str(y) for y in s.years_detail[:12])
        if len(s.years_detail) > 12:
            years_s += "…"
        tr.append(
            "<tr>"
            f"<td>{i}</td><td>{s.name}</td><td>{s.code}</td>"
            f'<td style="font-weight:600">{s.years_on_list}/{s.total_years}</td>'
            f'<td style="text-align:left;font-size:12px">{years_s}</td>'
            f"<td>{s.best_yield:.2f}%</td>"
            "</tr>"
        )
        md_rows.append(
            f"| {s.code} | {s.name} | **{s.years_on_list}/{s.total_years}** | "
            f"{years_s} | {s.best_yield:.2f}% |")

    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px 16px; }
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
<title>股息率榜单时长 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>占据股息率榜单时间最长的股票</h1>
<div class="meta">{as_of} · 统计区间 {years_range[0]}~{years_range[1]} ·
上榜规则：{rule} · 数据来源：东财分红送配报表（股息率小数口径 ×100）</div>
<div class="card"><table>
<tr><th>#</th><th>名称</th><th>代码</th><th>上榜/数据年数</th><th style="text-align:left">上榜年份</th><th>最高股息率</th></tr>
{''.join(tr) if tr else '<tr><td colspan="6" style="text-align:center;color:#86909c">无数据（数据源不可达时请本机运行）</td></tr>'}
</table></div>
<div class="footer">上榜时长反映分红稳定性；需结合分红可持续性与基本面。
不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 股息率榜单时长 {as_of}
date: {as_of}
tags: [股息率, 榜单, 分红稳定]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 占据股息率榜单时间最长的股票

统计区间 {years_range[0]}~{years_range[1]} · 上榜规则：{rule}

{chr(10).join(md_rows) if md_rows else "无数据。"}

> 不构成投资建议。
"""
    return html, md
