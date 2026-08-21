"""股权质押监控：上市公司股东股权质押/解除质押公告。

数据源：巨潮资讯 stock_cg_equity_mortgage_cninfo（按日期全市场质押公告）。
字段：出质人/质权人/质押数量/占总股本比例/质押解除数量。
过滤自选股，入库 SQLite（pledge 表，代码+日期+出质人去重）。

说明：高质押比例 → 爆仓/控制权风险信号；解除质押 → 压力缓解。
不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class Pledge:
    code: str
    name: str
    announce_date: str      # 公告日期
    pledger: str            # 出质人
    pledgee: str            # 质权人
    pledge_shares: float | None   # 质押数量（股）
    ratio: float | None           # 占总股本 %
    release_shares: float | None  # 质押解除数量（股）

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name,
            "announce_date": self.announce_date, "pledger": self.pledger,
            "pledgee": self.pledgee, "pledge_shares": self.pledge_shares,
            "ratio": self.ratio, "release_shares": self.release_shares,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_pledges(date: str | None = None) -> list[Pledge]:
    """拉取指定交易日全市场质押公告（缺省最近一个交易日，逐日回退）。"""
    import akshare as ak

    d = date or datetime.now().strftime("%Y%m%d")
    df = ak.stock_cg_equity_mortgage_cninfo(date=d)
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        rows.append(Pledge(
            code=str(r.get("股票代码") or ""),
            name=str(r.get("股票简称") or ""),
            announce_date=str(r.get("公告日期") or "")[:10],
            pledger=str(r.get("出质人") or ""),
            pledgee=str(r.get("质权人") or ""),
            pledge_shares=_f(r.get("质押数量")),
            ratio=_f(r.get("占总股本比例")),
            release_shares=_f(r.get("质押解除数量")),
        ))
    return rows


def scan_watchlist_pledges(cfg, days: int = 7) -> list[Pledge]:
    """扫描自选股近 days 天质押公告（逐日回退拉取）。"""
    codes = {str(it["code"]) for it in cfg.watchlist}
    names = {str(it.get("name", "")) for it in cfg.watchlist}
    hits = []
    for i in range(days):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            rows = fetch_pledges(d)
        except Exception as exc:  # noqa: BLE001
            logger.warning("质押扫描 %s 失败: %s", d, exc)
            continue
        for r in rows:
            if r.code in codes or any(n and n in r.name for n in names):
                hits.append(r)
    return hits


def build_pledge_report(rows: list[Pledge],
                        as_of: str | None = None) -> tuple[str, str]:
    """生成质押监控报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _shares(v: float | None) -> str:
        if v is None:
            return "-"
        if abs(v) >= 1e8:
            return f"{v / 1e8:.2f} 亿股"
        if abs(v) >= 1e4:
            return f"{v / 1e4:.0f} 万股"
        return f"{v:.0f} 股"

    tr = []
    md_rows = [
        "| 公告日 | 标的 | 出质人 | 质权人 | 质押数量 | 占比 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for x in rows:
        tr.append(
            "<tr>"
            f"<td>{x.announce_date}</td><td>{x.name}({x.code})</td>"
            f'<td style="text-align:left">{x.pledger}</td>'
            f'<td style="text-align:left">{x.pledgee}</td>'
            f"<td>{_shares(x.pledge_shares)}</td>"
            f"<td>{x.ratio:.2f}%</td>" if x.ratio is not None else "<td>-</td>"
            "</tr>"
        )
        md_rows.append(
            f"| {x.announce_date} | {x.name}({x.code}) | {x.pledger} | "
            f"{x.pledgee} | {_shares(x.pledge_shares)} | "
            f"{x.ratio:.2f}%" if x.ratio is not None else
            f"| {x.announce_date} | {x.name}({x.code}) | {x.pledger} | "
            f"{x.pledgee} | {_shares(x.pledge_shares)} | - |"
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
<title>股权质押监控 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>股权质押监控（自选股）</h1>
<div class="meta">{as_of} · 数据来源：巨潮资讯</div>
<div class="card"><table>
<tr><th>公告日</th><th>标的</th><th style="text-align:left">出质人</th><th style="text-align:left">质权人</th><th>质押数量</th><th>占比</th></tr>
{''.join(tr) if tr else '<tr><td colspan="6" style="text-align:center;color:#86909c">近期无质押公告（或未达披露标准）</td></tr>'}
</table></div>
<div class="footer">高质押比例 → 爆仓/控制权风险信号。不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 股权质押监控 {as_of}
date: {as_of}
tags: [质押, 风险]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 股权质押监控 {as_of}

{chr(10).join(md_rows) if md_rows else "近期无质押公告。"}

> 高质押比例 → 爆仓/控制权风险信号，不构成投资建议。
"""
    return html, md
