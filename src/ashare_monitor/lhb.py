"""龙虎榜监控：自选股上榜（涨跌幅偏离/换手率/振幅榜）席位动向。

数据源：东财龙虎榜（akshare stock_lhb_detail_em，按日期区间全市场）。
过滤自选股，展示上榜原因与机构/游资席位。
不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class LHBRecord:
    code: str
    name: str
    date: str
    reason: str
    close: float | None
    change_pct: float | None
    buy_amount: float | None      # 买入总额（元）
    sell_amount: float | None
    net_amount: float | None
    buy_org: str                  # 买入营业部

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "date": self.date,
            "reason": self.reason, "close": self.close,
            "change_pct": self.change_pct, "buy_amount": self.buy_amount,
            "sell_amount": self.sell_amount, "net_amount": self.net_amount,
            "buy_org": self.buy_org,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def scan_lhb(cfg, days: int = 10) -> list[LHBRecord]:
    """扫描自选股近 days 天龙虎榜。"""
    import akshare as ak

    codes = {str(it["code"]) for it in cfg.watchlist}
    hits: list[LHBRecord] = []
    for i in range(days):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = ak.stock_lhb_detail_em(start_date=d, end_date=d)
        except Exception as exc:  # noqa: BLE001
            logger.warning("龙虎榜 %s 失败: %s", d, exc)
            continue
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            code = str(r.get("代码") or r.get("股票代码") or "")
            if code not in codes:
                continue
            hits.append(LHBRecord(
                code=code,
                name=str(r.get("名称") or r.get("股票简称") or ""),
                date=str(r.get("上榜日") or r.get("日期") or d)[:10],
                reason=str(r.get("解读") or r.get("上榜原因") or ""),
                close=_f(r.get("收盘价")),
                change_pct=_f(r.get("涨跌幅")),
                buy_amount=_f(r.get("龙虎榜买入额")),
                sell_amount=_f(r.get("龙虎榜卖出额")),
                net_amount=_f(r.get("龙虎榜净买额")),
                buy_org=str(r.get("买入营业部") or ""),
            ))
    return hits


def build_lhb_report(rows: list[LHBRecord],
                     as_of: str | None = None) -> tuple[str, str]:
    """生成龙虎榜报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _amt(v: float | None) -> str:
        if v is None:
            return "-"
        return f"{v / 1e8:.2f} 亿" if abs(v) >= 1e8 else f"{v / 1e4:.0f} 万"

    tr = []
    md_rows = [
        "| 日期 | 标的 | 涨跌幅 | 上榜原因 | 净买额 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for x in rows:
        chg = f"{x.change_pct:+.2f}%" if x.change_pct is not None else "-"
        tr.append(
            "<tr>"
            f"<td>{x.date}</td><td>{x.name}({x.code})</td>"
            f"<td>{chg}</td>"
            f'<td style="text-align:left">{x.reason[:36]}</td>'
            f"<td>{_amt(x.net_amount)}</td>"
            "</tr>"
        )
        md_rows.append(f"| {x.date} | {x.name}({x.code}) | {chg} | "
                       f"{x.reason[:36]} | {_amt(x.net_amount)} |")

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
<title>龙虎榜监控 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>龙虎榜监控（自选股）</h1>
<div class="meta">{as_of} · 数据来源：东财龙虎榜</div>
<div class="card"><table>
<tr><th>日期</th><th>标的</th><th>涨跌幅</th><th style="text-align:left">上榜原因</th><th>净买额</th></tr>
{''.join(tr) if tr else '<tr><td colspan="5" style="text-align:center;color:#86909c">近 10 天无自选股上榜</td></tr>'}
</table></div>
<div class="footer">龙虎榜反映游资/机构短线动向。不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 龙虎榜监控 {as_of}
date: {as_of}
tags: [龙虎榜, 资金]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 龙虎榜监控 {as_of}

{chr(10).join(md_rows) if md_rows else "近 10 天无自选股上榜。"}

> 不构成投资建议。
"""
    return html, md
