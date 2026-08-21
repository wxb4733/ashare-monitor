"""大宗交易监控：自选股大宗交易（折溢率与买卖营业部）。

数据源：东财大宗交易（akshare stock_dzjy_mrmx，按日期区间）。
字段：收盘价/成交价/折溢率/成交额/买卖营业部。
折价深 → 抛压信号；溢价 → 积极信号。
不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class BlockTrade:
    code: str
    name: str
    date: str
    close: float | None
    price: float | None
    premium: float | None      # 折溢率 %
    volume: float | None
    amount: float | None
    buy_org: str
    sell_org: str

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "date": self.date,
            "close": self.close, "price": self.price,
            "premium": self.premium, "volume": self.volume,
            "amount": self.amount, "buy_org": self.buy_org,
            "sell_org": self.sell_org,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def scan_block_trades(cfg, days: int = 10) -> list[BlockTrade]:
    """扫描自选股近 days 天大宗交易。"""
    import akshare as ak

    codes = {str(it["code"]) for it in cfg.watchlist}
    end = datetime.now()
    start = end - timedelta(days=days)
    hits: list[BlockTrade] = []
    try:
        df = ak.stock_dzjy_mrmx(
            symbol="A股", start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("大宗交易失败: %s", exc)
        return hits
    if df is None or df.empty:
        return hits
    for _, r in df.iterrows():
        code = str(r.get("证券代码") or "")
        if code not in codes:
            continue
        hits.append(BlockTrade(
            code=code, name=str(r.get("证券简称") or ""),
            date=str(r.get("交易日期") or "")[:10],
            close=_f(r.get("收盘价")), price=_f(r.get("成交价")),
            premium=_f(r.get("折溢率")), volume=_f(r.get("成交量")),
            amount=_f(r.get("成交额")),
            buy_org=str(r.get("买方营业部") or ""),
            sell_org=str(r.get("卖方营业部") or ""),
        ))
    hits.sort(key=lambda x: x.date, reverse=True)
    return hits


def build_block_report(rows: list[BlockTrade],
                       as_of: str | None = None) -> tuple[str, str]:
    """生成大宗交易报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _fmt(v, nd: int = 2, suffix: str = "") -> str:
        return f"{v:.{nd}f}{suffix}" if v is not None else "-"

    tr = []
    md_rows = [
        "| 日期 | 标的 | 成交价 | 折溢率 | 成交额 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for x in rows:
        p = x.premium
        color = "#e02e24" if (p or 0) >= 0 else "#00a870"
        prem_cell = (f'<span style="color:{color}">{_fmt(p, 2, "%")}</span>'
                     if p is not None else "-")
        tr.append(
            "<tr>"
            f"<td>{x.date}</td><td>{x.name}({x.code})</td>"
            f"<td>{_fmt(x.price)}</td>"
            f"<td>{prem_cell}</td>"
            f"<td>{_fmt(x.amount and x.amount / 1e8, 2, ' 亿')}</td>"
            "</tr>"
        )
        md_rows.append(f"| {x.date} | {x.name}({x.code}) | {_fmt(x.price)} | "
                       f"{_fmt(p, 2, '%')} | {_fmt(x.amount and x.amount / 1e8, 2, ' 亿')} |")

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
<title>大宗交易 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>大宗交易监控（自选股）</h1>
<div class="meta">{as_of} · 数据来源：东财大宗交易 · 折价(绿)为抛压信号 / 溢价(红)为积极信号</div>
<div class="card"><table>
<tr><th>日期</th><th>标的</th><th>成交价</th><th>折溢率</th><th>成交额</th></tr>
{''.join(tr) if tr else '<tr><td colspan="5" style="text-align:center;color:#86909c">近 10 天无自选股大宗交易</td></tr>'}
</table></div>
<div class="footer">不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 大宗交易 {as_of}
date: {as_of}
tags: [大宗交易, 资金]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 大宗交易监控 {as_of}

{chr(10).join(md_rows) if md_rows else "近 10 天无自选股大宗交易。"}

> 折价深 → 抛压信号，不构成投资建议。
"""
    return html, md
