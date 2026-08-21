"""上市公司诉讼监控：以指定股票代码对应公司的重大诉讼披露。

数据源：巨潮资讯（webapi.cninfo.com.cn p_sysapi1055，经 akshare）
覆盖范围：累计诉讼金额达到披露标准的公司（近 N 天公告统计）。
字段：证券代码/简称/公告统计区间/诉讼次数/诉讼金额（万元）。
入库 SQLite（litigation 表，code+period 去重）供历史追踪。

说明：该接口仅覆盖「达到重大诉讼披露标准」的公司——未出现在列表中
表示近 N 天无重大诉讼披露（如实）。详细个案诉讼需裁判文书网（反爬）或
天眼查/企查查（连接器）。

声明：公开信息整理，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class Lawsuit:
    code: str
    name: str
    period: str       # 公告统计区间
    count: int        # 诉讼次数
    amount: float | None  # 诉讼金额（万元）
    fetched_at: str

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "period": self.period,
            "count": self.count, "amount": self.amount,
            "fetched_at": self.fetched_at,
        }


def fetch_all_lawsuits(days: int = 365) -> list[Lawsuit]:
    """拉取全市场重大诉讼披露（近 days 天）。"""
    import akshare as ak

    end = datetime.now()
    start = end - timedelta(days=days)
    end_s = end.strftime("%Y%m%d")
    start_s = start.strftime("%Y%m%d")
    df = ak.stock_cg_lawsuit_cninfo(
        symbol="全部", start_date=start_s, end_date=end_s,
    )
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        amount = _f(r.get("诉讼金额"))
        rows.append(Lawsuit(
            code=str(r.get("证券代码") or ""),
            name=str(r.get("证券简称") or ""),
            period=str(r.get("公告统计区间") or ""),
            count=int(r.get("诉讼次数") or 0),
            amount=amount,
            fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
    return rows


def _f(v) -> float | None:
    try:
        if v is None or v == "" or str(v).lower() in ("nan", "--"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def scan_watchlist_lawsuits(cfg, days: int = 365) -> list[Lawsuit]:
    """扫描自选股的重大诉讼披露。"""
    all_rows = fetch_all_lawsuits(days=days)
    names = {str(it.get("name", "")) for it in cfg.watchlist}
    codes = {str(it["code"]) for it in cfg.watchlist}
    hits = []
    for r in all_rows:
        if r.code in codes or any(n and n in r.name for n in names):
            hits.append(r)
    return hits


def save_lawsuits(rows: list[Lawsuit]) -> int:
    """入库去重（code+period 唯一），返回新增条数。"""
    from .storage import get_conn

    conn = get_conn()
    added = 0
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS litigation (
                code TEXT, name TEXT, period TEXT, count INT,
                amount REAL, fetched_at TEXT,
                PRIMARY KEY (code, period))"""
        )
        for r in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO litigation "
                "(code, name, period, count, amount, fetched_at) "
                "VALUES (?,?,?,?,?,?)",
                (r.code, r.name, r.period, r.count, r.amount, r.fetched_at),
            )
            added += cur.rowcount
    return added


def load_saved_lawsuits(code: str | None = None) -> list[Lawsuit]:
    """读取已入库诉讼（最新在前）。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM litigation"
    params: tuple = ()
    if code:
        sql += " WHERE code = ?"
        params = (code,)
    sql += " ORDER BY fetched_at DESC LIMIT 50"
    rows = []
    for r in conn.execute(sql, params).fetchall():
        rows.append(Lawsuit(
            code=r["code"], name=r["name"], period=r["period"],
            count=r["count"], amount=r["amount"], fetched_at=r["fetched_at"],
        ))
    return rows


def build_litigation_report(rows: list[Lawsuit], days: int,
                            as_of: str | None = None) -> tuple[str, str]:
    """生成诉讼监控报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _amt(v: float | None) -> str:
        if v is None:
            return "-"
        if abs(v) >= 10000:
            return f"{v / 10000:.2f} 亿"
        return f"{v:.0f} 万"

    tr = []
    md_rows = [
        "| 代码 | 简称 | 统计区间 | 诉讼次数 | 诉讼金额 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        tr.append(
            "<tr>"
            f"<td>{r.code}</td><td>{r.name}</td>"
            f"<td>{r.period}</td><td>{r.count}</td>"
            f"<td>{_amt(r.amount)}</td>"
            "</tr>"
        )
        md_rows.append(
            f"| {r.code} | {r.name} | {r.period} | {r.count} | {_amt(r.amount)} |"
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
<title>诉讼监控 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>上市公司诉讼监控（自选股）</h1>
<div class="meta">{as_of} · 近 {days} 天 · 数据来源：巨潮资讯 · 金额单位：万元/亿</div>
<div class="card"><table>
<tr><th>代码</th><th>简称</th><th>统计区间</th><th>诉讼次数</th><th>诉讼金额</th></tr>
{''.join(tr) if tr else '<tr><td colspan="5" style="text-align:center;color:#86909c">近 ' + str(days) + ' 天无重大诉讼披露（或未达披露标准）</td></tr>'}
</table></div>
<div class="footer">仅覆盖达到重大诉讼披露标准的公司；个案详情需裁判文书网或企业数据库。不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 诉讼监控 {as_of}
date: {as_of}
tags: [诉讼, 法律风险]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 上市公司诉讼监控（近 {days} 天）

{chr(10).join(md_rows) if md_rows else "近 " + str(days) + " 天无重大诉讼披露。"}

> 仅覆盖达到重大诉讼披露标准的公司，不构成投资建议。
"""
    return html, md
