"""北向持股监控：自选股陆股通持股数量与占比变化。

数据源：东财（akshare stock_hsgt_individual_em，2017 年起历史序列）。
注意：2024-08-16 起北向净买入额度与个股持股明细均停止每日披露（监管调整），
历史数据保留，最新披露日停在 2024-08-16。
字段：持股数量/占A股比例/今日增持。
不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class NorthHolding:
    code: str
    name: str
    date: str
    hold_shares: float | None    # 持股数量
    hold_ratio: float | None     # 占 A 股 %
    today_add: float | None      # 今日增持数量
    today_amount: float | None   # 今日增持资金

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "date": self.date,
            "hold_shares": self.hold_shares, "hold_ratio": self.hold_ratio,
            "today_add": self.today_add, "today_amount": self.today_amount,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_north(code: str) -> list[NorthHolding]:
    """北向持股历史（最新在前）。"""
    import akshare as ak

    df = ak.stock_hsgt_individual_em(symbol=code)
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        rows.append(NorthHolding(
            code=code, name="", date=str(r.get("持股日期") or "")[:10],
            hold_shares=_f(r.get("持股数量")),
            hold_ratio=_f(r.get("持股数量占A股百分比")),
            today_add=_f(r.get("今日增持股数")),
            today_amount=_f(r.get("今日增持资金")),
        ))
    rows.reverse()  # 最新在前
    return rows


def scan_watchlist_north(cfg, codes: list[str] | None = None) -> dict[str, list[NorthHolding]]:
    """扫描自选股北向持股（A 股）。"""
    result = {}
    for it in cfg.watchlist:
        if str(it.get("market", "ashare")) != "ashare":
            continue
        c = str(it["code"])
        if codes and c not in codes:
            continue
        try:
            rows = fetch_north(c)
            if rows:
                result[c] = rows
        except Exception as exc:  # noqa: BLE001
            logger.warning("北向 %s 失败: %s", c, exc)
    return result


def build_north_report(data: dict[str, list[NorthHolding]],
                       as_of: str | None = None) -> tuple[str, str]:
    """生成北向持股报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _shares(v: float | None) -> str:
        if v is None:
            return "-"
        return f"{v / 1e8:.2f} 亿" if abs(v) >= 1e8 else f"{v / 1e4:.0f} 万"

    tr = []
    md_rows = [
        "| 标的 | 日期 | 持股数量 | 占A股% | 今日增持 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for code, rows in data.items():
        latest = rows[0]
        add = latest.today_add
        add_cell = (f'<span style="color:{"#e02e24" if add and add > 0 else "#00a870"}">'
                    f"{_shares(add)}</span>" if add is not None else "-")
        tr.append(
            "<tr>"
            f"<td>{code}</td><td>{latest.date}</td>"
            f"<td>{_shares(latest.hold_shares)}</td>"
            f"<td>{latest.hold_ratio:.2f}%</td>"
            f"<td>{add_cell}</td>"
            "</tr>"
        )
        md_rows.append(f"| {code} | {latest.date} | {_shares(latest.hold_shares)} | "
                       f"{latest.hold_ratio:.2f}% | {_shares(add)} |")

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
<title>北向持股 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>北向持股监控（自选股）</h1>
<div class="meta">{as_of} · 数据来源：东财（个股持股明细自 2024-08-16 起停止每日披露，历史数据保留）</div>
<div class="card"><table>
<tr><th>标的</th><th>日期</th><th>持股数量</th><th>占A股%</th><th>今日增持</th></tr>
{''.join(tr) if tr else '<tr><td colspan="5" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<div class="footer">不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 北向持股 {as_of}
date: {as_of}
tags: [北向, 资金]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 北向持股监控 {as_of}

{chr(10).join(md_rows) if md_rows else "无数据。"}

> 不构成投资建议。
"""
    return html, md
