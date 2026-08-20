"""持仓管理与盈亏日报。

持仓数据来自 config.local.yaml 的 `positions` 列表（含成本价，隐私数据不入 git）：
```yaml
positions:
  - code: "002594"          # A 股 6 位 / 港股 5 位
    market: "ashare"        # ashare / hk
    name: "比亚迪"           # 可选，缺省用行情名称
    cost: 88.0              # 成本价（元 / 港元）
    shares: 1000            # 持仓数量（股）
```

现价来源：默认本地回填 K 线最新收盘（收盘后准确、离线快速），--live 时用实时行情。
盈亏按最新价与成本价计算；港股持仓标注港元。

声明：持仓盈亏为个人记录与行情统计，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Position:
    code: str
    name: str
    market: str
    cost: float        # 成本价
    shares: float      # 持仓数量
    price: float | None = None      # 最新价（缺失时盈亏为 None）
    change_pct: float | None = None  # 最新价当日涨跌幅 %

    @property
    def market_value(self) -> float | None:
        return self.price * self.shares if self.price is not None else None

    @property
    def cost_value(self) -> float:
        return self.cost * self.shares

    @property
    def pnl(self) -> float | None:
        if self.price is None:
            return None
        return (self.price - self.cost) * self.shares

    @property
    def pnl_pct(self) -> float | None:
        if self.price is None or self.cost <= 0:
            return None
        return (self.price / self.cost - 1) * 100

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "market": self.market,
            "cost": self.cost, "shares": self.shares,
            "price": self.price, "change_pct": self.change_pct,
            "market_value": self.market_value, "cost_value": self.cost_value,
            "pnl": self.pnl, "pnl_pct": self.pnl_pct,
        }


def load_positions(cfg) -> list[Position]:
    """从配置读取持仓列表。"""
    positions = []
    for it in cfg.positions or []:
        code = str(it.get("code", ""))
        if not code:
            continue
        market = str(it.get("market", "ashare"))
        positions.append(Position(
            code=code,
            name=str(it.get("name", code)),
            market=market,
            cost=float(it.get("cost", 0.0)),
            shares=float(it.get("shares", 0.0)),
        ))
    return positions


def _latest_close(code: str, market: str) -> tuple[float, str] | None:
    """本地 K 线最新收盘（返回 价格, 日期）。"""
    from .storage import load_klines

    rows = load_klines(code, market)
    if not rows:
        return None
    return float(rows[-1]["close"]), rows[-1]["date"]


def _live_quote(code: str, market: str) -> tuple[float, float] | None:
    """实时行情（返回 价格, 涨跌幅%）。"""
    from .quotes import fetch_quotes

    quotes = fetch_quotes([{"code": code, "market": market}])
    if quotes and quotes[0].price is not None:
        return quotes[0].price, quotes[0].change_pct or 0.0
    return None


def fill_prices(positions: list[Position], live: bool = False) -> tuple[list[Position], str]:
    """填充最新价。返回 (positions, 价格基准说明)。"""
    as_of = ""
    for p in positions:
        try:
            if live:
                got = _live_quote(p.code, p.market)
                if got:
                    p.price, p.change_pct = got
            else:
                got = _latest_close(p.code, p.market)
                if got:
                    p.price, p.change_pct = got[0], None
                    as_of = got[1]
        except Exception as exc:  # noqa: BLE001
            logger.warning("持仓 %s 行情获取失败: %s", p.code, exc)
    return positions, as_of


def build_position_report(positions: list[Position], as_of: str | None = None,
                          live: bool = False) -> tuple[str, str]:
    """生成持仓盈亏报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _fmt(v, suffix: str = "", nd: int = 2, sign: bool = False) -> str:
        if v is None:
            return "-"
        return f"{v:+.{nd}f}{suffix}" if sign else f"{v:.{nd}f}{suffix}"

    def _cls(v: float | None, up_good: bool = True) -> str:
        if v is None or v == 0:
            return ""
        positive = v > 0
        good = positive if up_good else not positive
        return "up" if good else "down"

    total_cost = sum(p.cost_value for p in positions)
    total_value = sum(p.market_value for p in positions if p.market_value is not None)
    total_pnl = total_value - total_cost if total_value else None
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost and total_pnl is not None else None

    tr = []
    md_rows = [
        "| 标的 | 市场 | 成本价 | 现价 | 持仓(股) | 市值 | 盈亏额 | 盈亏率 | 仓位占比 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p in positions:
        currency = "港元" if p.market == "hk" else "元"
        weight = (p.market_value / total_value * 100) if p.market_value and total_value else None
        tr.append(
            "<tr>"
            f"<td>{p.name}({p.code})</td><td>{p.market}</td>"
            f"<td>{_fmt(p.cost)}</td><td>{_fmt(p.price)}</td>"
            f"<td>{p.shares:,.0f}</td>"
            f"<td>{_fmt(p.market_value)}</td>"
            f'<td class="{_cls(p.pnl)}">{_fmt(p.pnl, sign=True)}</td>'
            f'<td class="{_cls(p.pnl_pct)}">{_fmt(p.pnl_pct, "%", 1, sign=True)}</td>'
            f"<td>{_fmt(weight, '%', 1)}</td>"
            "</tr>"
        )
        md_rows.append(
            f"| {p.name}({p.code}) | {p.market} | {_fmt(p.cost)} | {_fmt(p.price)} | "
            f"{p.shares:,.0f} | {_fmt(p.market_value)} | {_fmt(p.pnl, sign=True)} | "
            f"{_fmt(p.pnl_pct, '%', 1, sign=True)} | {_fmt(weight, '%', 1)} |"
        )
    tr.append(
        "<tr style=\"font-weight:600\">"
        f"<td colspan=\"5\">合计（{currency_hint(positions)}）</td>"
        f"<td>{_fmt(total_value)}</td>"
        f'<td class="{_cls(total_pnl)}">{_fmt(total_pnl, sign=True)}</td>'
        f'<td class="{_cls(total_pnl_pct)}">{_fmt(total_pnl_pct, "%", 1, sign=True)}</td>'
        "<td>100%</td></tr>"
    )
    md_rows.append(
        f"| **合计** | - | - | - | - | {_fmt(total_value)} | "
        f"{_fmt(total_pnl, sign=True)} | {_fmt(total_pnl_pct, '%', 1, sign=True)} | 100% |"
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
.up { color: #e02e24; } .down { color: #00a870; }
.footer { color: #86909c; font-size: 12px; text-align: center; padding: 16px 0 8px; }
"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>持仓盈亏 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>持仓盈亏日报</h1>
<div class="meta">{as_of} · {'实时行情' if live else '收盘价'} · 单位：A 股人民币 / 港股港元 · 涨红跌绿</div>
<div class="card"><table>
<tr><th>标的</th><th>市场</th><th>成本价</th><th>现价</th><th>持仓(股)</th><th>市值</th><th>盈亏额</th><th>盈亏率</th><th>仓位占比</th></tr>
{''.join(tr)}
</table></div>
<div class="footer">持仓为个人记录，数据仅供学习，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 持仓盈亏 {as_of}
date: {as_of}
tags: [持仓, 盈亏]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 持仓盈亏日报 {as_of}

{'实时行情' if live else '收盘价'}。单位：A 股人民币 / 港股港元。

{chr(10).join(md_rows)}

> 持仓为个人记录，数据仅供学习，不构成投资建议。
"""
    return html, md


def currency_hint(positions: list[Position]) -> str:
    """合计币种提示：全部同市场则标该币种，混合标"混合"。"""
    markets = {p.market for p in positions}
    if markets == {"hk"}:
        return "港元"
    if markets == {"ashare"}:
        return "人民币"
    return "混合"
