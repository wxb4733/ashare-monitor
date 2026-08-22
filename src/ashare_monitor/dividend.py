"""历史股息率回填与查询。

数据源：东财分红送配报表（stock_fhps_em，按年度全市场）+ 本地 K 线年末价。
算法：年度每股派息（同一年多次分红累加，现金分红比例=每 10 股派息元）
      / 该年度末收盘价 → 年度股息率 %。
入库 SQLite（dividend_history：code, year, dps, year_end_price, yield_pct）。

用途：股息率 5 年历史 / 当前股息率分位 / 分红持续性判断。
说明：东财分红报表在部分沙箱网络不可用（已知），本机直连通常可用；
年份缺分红记录时如实标注。不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# A 股 1990 年开市（上交所），至今不足 40 年——按开市以来全历史回填
YEARS = list(range(1990, datetime.now().year + 1))


@dataclass
class DividendYear:
    code: str
    name: str
    year: int
    dps: float | None            # 年度每股派息（元）
    year_end_price: float | None
    yield_pct: float | None      # 年度股息率 %
    n_payments: int = 0          # 年内分红次数

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "year": self.year,
            "dps": self.dps, "year_end_price": self.year_end_price,
            "yield_pct": self.yield_pct, "n_payments": self.n_payments,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", "", "none"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _year_end_price(code: str) -> dict[int, float]:
    """本地 K 线每年末收盘价。"""
    from .storage import load_klines

    result: dict[int, float] = {}
    try:
        rows = load_klines(code, "ashare")
    except Exception:  # noqa: BLE001
        return result
    by_year: dict[int, float] = {}
    for r in rows:
        try:
            y = int(str(r["date"])[:4])
            by_year[y] = float(r["close"])  # 最后写入即年末
        except (ValueError, KeyError):
            continue
    return by_year


def fetch_dividend_history(code: str, name: str = "") -> list[DividendYear]:
    """回填单只 A 股年度股息率历史（近 6 年）。"""
    import akshare as ak

    # 1. 拉各年分红方案（东财报表按年度查询）
    yearly_dps: dict[int, float] = {}
    yearly_n: dict[int, int] = {}
    for year in YEARS:
        try:
            df = ak.stock_fhps_em(date=f"{year}1231")
        except Exception as exc:  # noqa: BLE001
            logger.warning("分红报表 %s 失败: %s", year, exc)
            continue
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            if str(r.get("股票代码") or "") != code:
                continue
            dps10 = _f(r.get("现金分红-现金分红比例"))
            if dps10 is None:
                continue
            dps = dps10 / 10.0
            yearly_dps[year] = yearly_dps.get(year, 0.0) + dps
            yearly_n[year] = yearly_n.get(year, 0) + 1

    # 2. 结合年末价算股息率
    year_prices = _year_end_price(code)
    result = []
    for year in YEARS:
        dps = yearly_dps.get(year)
        price = year_prices.get(year)
        yield_pct = (dps / price * 100) if dps is not None and price else None
        result.append(DividendYear(
            code=code, name=name, year=year, dps=dps,
            year_end_price=price, yield_pct=yield_pct,
            n_payments=yearly_n.get(year, 0),
        ))
    return result


def save_dividend_history(rows: list[DividendYear]) -> int:
    """入库（code+year 唯一），返回新增。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    added = 0
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS dividend_history (
                code TEXT, name TEXT, year INTEGER,
                dps REAL, year_end_price REAL, yield_pct REAL,
                n_payments INTEGER, PRIMARY KEY (code, year))"""
        )
        for r in rows:
            cur = conn.execute(
                "INSERT OR REPLACE INTO dividend_history "
                "(code, name, year, dps, year_end_price, yield_pct, n_payments) "
                "VALUES (?,?,?,?,?,?,?)",
                (r.code, r.name, r.year, r.dps, r.year_end_price,
                 r.yield_pct, r.n_payments),
            )
            added += cur.rowcount
    return added


def load_dividend_history(code: str) -> list[DividendYear]:
    """读取已入库历史。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = []
    for r in conn.execute(
        "SELECT * FROM dividend_history WHERE code=? ORDER BY year",
        (code,),
    ).fetchall():
        rows.append(DividendYear(
            code=r["code"], name=r["name"], year=r["year"], dps=r["dps"],
            year_end_price=r["year_end_price"], yield_pct=r["yield_pct"],
            n_payments=r["n_payments"],
        ))
    return rows


def build_dividend_report(hist: dict[str, list[DividendYear]],
                          as_of: str | None = None) -> tuple[str, str]:
    """生成历史股息率报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    tr = []
    md_rows = ["| 标的 | 年份 | 每股派息 | 年末价 | 股息率 | 分红次数 |",
               "| --- | --- | --- | --- | --- | --- |"]
    for code, rows in hist.items():
        name = rows[0].name if rows else code
        valid = [r for r in rows if r.yield_pct is not None]
        latest = valid[-1].yield_pct if valid else None
        avg = sum(r.yield_pct for r in valid) / len(valid) if valid else None
        # 只展示有分红记录的年份（全历史可能 36 年，空行压缩）
        paid = [r for r in rows if r.dps is not None]
        display = paid if paid else rows[-3:] if rows else []
        span = max(len(display), 1)
        summary = (f"<br/><span style='color:#86909c;font-size:11px'>"
                   f"最新 {latest:.2f}% / 均值 {avg:.2f}% / "
                   f"分红 {len(paid)} 年"
                   f"</span>")
        head = (f"<tr><td rowspan='{span}'>{name}({code}){summary if valid else ''}</td>")
        for i, r in enumerate(display):
            dps = f"{r.dps:.3f}" if r.dps is not None else "-"
            price = f"{r.year_end_price:.2f}" if r.year_end_price is not None else "-"
            yp = (f'<span style="color:#e02e24;font-weight:600">{r.yield_pct:.2f}%</span>'
                  if r.yield_pct is not None else "-")
            row = f"<tr><td>{r.year}</td><td>{dps}</td><td>{price}</td>" \
                  f"<td>{yp}</td><td>{r.n_payments}</td></tr>"
            if i == 0:
                row = head + f"<td>{r.year}</td><td>{dps}</td>" \
                              f"<td>{price}</td><td>{yp}</td>" \
                              f"<td>{r.n_payments}</td></tr>"
            tr.append(row)
        if not display:
            tr.append(f"<tr><td>{name}({code})</td><td colspan='5' "
                      f"style='text-align:center;color:#86909c'>无分红数据</td></tr>")
        md_rows.append(
            f"| {name}({code}) | 最新 {latest:.2f}% / 均值 {avg:.2f}% / "
            f"分红 {len(paid)} 年 |" if valid else
            f"| {name}({code}) | 无分红数据 |")
        for r in display:
            dps_s = f"{r.dps:.3f}" if r.dps is not None else "-"
            yp_s = f"{r.yield_pct:.2f}%" if r.yield_pct is not None else "-"
            price_s = (f"{r.year_end_price:.2f}"
                       if r.year_end_price is not None else "-")
            md_rows.append(f"| {name}({code}) | {r.year} | {dps_s} | "
                           f"{price_s} | {yp_s} | {r.n_payments} |")

    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }
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
<title>历史股息率 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>历史股息率（自 1990 年开市以来）</h1>
<div class="meta">{as_of} · 年度每股派息/年末价；分红多次累加；涨红跌绿</div>
<div class="card"><table>
<tr><th>标的</th><th>年份</th><th>每股派息</th><th>年末价</th><th>股息率</th><th>分红次数</th></tr>
{''.join(tr) if tr else '<tr><td colspan="6" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<div class="footer">股息率 = 年度每股派息/年末价；分红可持续性需结合基本面。
不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 历史股息率 {as_of}
date: {as_of}
tags: [股息率, 分红]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 历史股息率 {as_of}

{chr(10).join(md_rows) if md_rows else "无数据。"}

> 不构成投资建议。
"""
    return html, md
