"""个股全方位体检：一键汇总行情/技术/基本面/筹码/资金/事件/择时/命中率。

对指定代码运行全部现有分析模块，规则化评分（0-100 每维），输出总分、
各维明细、亮点与风险提示。评分是规则化的参考信息，不构成投资建议。

权重：技术 25% / 基本面 25% / 筹码 20% / 资金 15% / 事件 15%。
数据源：本地 K 线 + 东财直连（财报/股东/资金/事件）+ 实时行情（失败降级本地）。
任何维度失败不阻塞，标注「数据缺失」并按中性 50 分计入。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Dimension:
    key: str
    label: str
    score: float | None      # 0-100，None=数据缺失
    detail: str = ""
    notes: list[str] = field(default_factory=list)  # 亮点/风险

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "score": self.score,
            "detail": self.detail, "notes": self.notes,
        }


WEIGHTS = {"technical": 0.25, "fundamental": 0.25, "chip": 0.20,
           "fundflow": 0.15, "event": 0.15}


def _technical(rows: list[dict], price: float) -> Dimension:
    """技术面：基于本地 K 线指标状态。"""
    import pandas as pd

    from .indicators import boll, kdj, macd, rsi

    close_s = pd.Series([float(r["close"]) for r in rows])
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    dates = [r["date"] for r in rows]
    closes = close_s.tolist()
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None
    m = macd(close_s, dates=pd.Series(dates))
    r = rsi(close_s)
    k = kdj(close_s, pd.Series(highs), pd.Series(lows))
    b = boll(close_s, price)

    pts = 0
    notes = []
    parts = []
    if ma20:
        parts.append(f"MA20 {ma20:.2f}")
        if price > ma20:
            pts += 1
            notes.append("站上 MA20")
        else:
            notes.append("跌破 MA20")
    if ma60:
        parts.append(f"MA60 {ma60:.2f}")
        if price > ma60:
            pts += 1
            notes.append("站上 MA60")
        if ma20 > ma60:
            pts += 1
            notes.append("MA20 上穿 MA60（多头排列）")
    if m.trend == "金叉":
        pts += 1
        notes.append(f"MACD 金叉（{m.days_since_cross} 日前）")
    elif m.trend == "死叉":
        notes.append("MACD 死叉")
    if r.value is not None:
        parts.append(f"RSI {r.value:.0f}")
        if 40 <= r.value <= 70:
            pts += 1
    if k.trend == "金叉" or (k.k is not None and k.d is not None and k.k > k.d):
        pts += 1
        notes.append("KDJ 多头")
    score = round(pts / 5 * 100) if pts <= 5 else 100
    return Dimension("technical", "技术面", score,
                     "；".join(parts) or "数据不足", notes)


def _fundamental(code: str) -> Dimension:
    """基本面：最新财报 ROE/净利增速/毛利率。"""
    try:
        from .fundamentals import fetch_financials

        ps = fetch_financials(code, periods=2)
    except Exception as exc:  # noqa: BLE001
        logger.warning("体检基本面失败: %s", exc)
        return Dimension("fundamental", "基本面", None, "数据缺失")
    if not ps:
        return Dimension("fundamental", "基本面", None, "无财报数据")
    p = ps[0]
    score = 50.0
    parts = []
    if p.roe is not None:
        parts.append(f"ROE {p.roe:.1f}%")
        score = 60 if p.roe >= 15 else (40 if p.roe >= 8 else 20)
    if p.profit_yoy is not None:
        parts.append(f"净利同比 {p.profit_yoy:+.1f}%")
        if p.profit_yoy > 0:
            score += 20
        if p.profit_yoy > 20:
            score += 10
    if p.gross_margin is not None:
        parts.append(f"毛利率 {p.gross_margin:.1f}%")
        if p.gross_margin >= 30:
            score += 10
    if p.revenue_yoy is not None:
        parts.append(f"营收同比 {p.revenue_yoy:+.1f}%")
    score = round(min(score, 100))
    return Dimension("fundamental", "基本面", score,
                     f"{p.report_date} " + "；".join(parts))


def _chip(code: str) -> Dimension:
    """筹码面：股东户数集中度。"""
    try:
        from .holders import concentration_status

        state, desc = concentration_status(code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("体检筹码失败: %s", exc)
        return Dimension("chip", "筹码", None, "数据缺失")
    if state is None:
        return Dimension("chip", "筹码", None, "无户数数据")
    score = {"集中": 100, "稳定": 65, "分散": 35}.get(state, 50)
    return Dimension("chip", "筹码", score, f"{state}；{desc}")


def _fundflow(code: str) -> Dimension:
    """资金面：主力净流入。"""
    try:
        from .fundflow import fetch_fundflow, fetch_fundflow_ak

        try:
            f = fetch_fundflow(code, "ashare", "")
        except Exception:  # noqa: BLE001 - push2 不稳降级
            f = fetch_fundflow_ak(code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("体检资金失败: %s", exc)
        return Dimension("fundflow", "资金", None, "数据缺失")
    if f.main_net is None:
        return Dimension("fundflow", "资金", None, "无资金流数据")
    m = f.main_net
    if m > 1:
        score, note = 90, f"主力净流入 {m:+.2f} 亿（强）"
    elif m > 0:
        score, note = 70, f"主力净流入 {m:+.2f} 亿"
    elif m < -1:
        score, note = 20, f"主力净流出 {m:+.2f} 亿（弱）"
    else:
        score, note = 40, f"主力净流出 {m:+.2f} 亿"
    return Dimension("fundflow", "资金", score, f"{f.date} {note}")


def _event(code: str) -> Dimension:
    """事件面：未来 30 天事件风险（解禁为风险）。"""
    try:
        from .events import fetch_events

        evs = fetch_events(code, "ashare", days=30)
    except Exception as exc:  # noqa: BLE001
        logger.warning("体检事件失败: %s", exc)
        return Dimension("event", "事件", None, "数据缺失")
    if not evs:
        return Dimension("event", "事件", 85, "未来 30 天无事件")
    score = 85
    notes = []
    for e in evs:
        if e.kind == "解禁":
            score = min(score, 35)
            notes.append(f"{e.date} 解禁：{e.detail}")
        elif e.kind == "业绩预告":
            score = min(score, 60)
            notes.append(f"{e.date} 业绩预告：{e.detail}")
        elif e.kind == "分红除权":
            score = min(score, 70)
            notes.append(f"{e.date} 分红除权：{e.detail}")
    return Dimension("event", "事件", score,
                     f"{len(evs)} 项事件", notes)


def run_doctor(code: str, market: str = "ashare", name: str = "") -> dict:
    """执行全方位体检。返回 {code, name, market, as_of, dims, total, verdict, quotes}。"""
    from .storage import load_klines

    dims: list[Dimension] = []

    # 行情/技术：本地 K 线（收盘价）+ 实时行情失败降级
    rows = load_klines(code, market) if market == "ashare" else load_klines(code, "hk")
    price, change_pct = None, None
    if rows:
        last = rows[-1]
        price = float(last["close"])
        prev = rows[-2]["close"] if len(rows) > 1 else price
        change_pct = (price / prev - 1) * 100 if prev else None
    try:  # 实时行情优先
        from .quotes import fetch_spot_quotes

        qs = fetch_spot_quotes([{"code": code, "market": market}])
        if qs and qs[0].price is not None:
            price = qs[0].price
            change_pct = qs[0].change_pct
    except Exception:  # noqa: BLE001
        pass

    dims.append(Dimension("quote", "行情", None,
                          f"现价 {price:.2f}（{change_pct:+.2f}%）" if price else "无行情"))
    if rows and len(rows) >= 60:
        dims.append(_technical(rows, price or float(rows[-1]["close"])))
    else:
        dims.append(Dimension("technical", "技术面", None, "K 线不足"))
    if market == "ashare":
        dims.append(_fundamental(code))
        dims.append(_chip(code))
        dims.append(_fundflow(code))
        dims.append(_event(code))
    else:
        for key, label in (("fundamental", "基本面"), ("chip", "筹码"),
                           ("fundflow", "资金"), ("event", "事件")):
            dims.append(Dimension(key, label, None, "港股暂不支持"))

    # 择时信号（附加，不计分）
    timing_notes = []
    try:
        from .timing import scan_timing

        for sg in scan_timing(rows, code, name or code, market):
            timing_notes.append(f"{sg.label}（历史命中率 {sg.win_rate:.0f}%）")
    except Exception:  # noqa: BLE001
        pass

    # 总分（加权；缺失维度按 50 中性计）
    total = 0.0
    used = 0
    for d in dims:
        if d.key == "quote" or d.key not in WEIGHTS:
            continue
        used += WEIGHTS[d.key]
        total += WEIGHTS[d.key] * (d.score if d.score is not None else 50)
    if used > 0:
        total = round(total / used)
    else:
        total = None
    verdict = "强势" if (total or 0) >= 70 else ("中性" if (total or 0) >= 55 else "谨慎")

    # 风险提示汇总
    risks = []
    for d in dims:
        if d.score is not None and d.score < 40:
            risks.append(f"{d.label}({d.score}分): {d.detail}")
    highlights = []
    for d in dims:
        if d.score is not None and d.score >= 70:
            highlights.append(f"{d.label}({d.score}分): {d.detail}")

    return {
        "code": code, "name": name or code, "market": market,
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "price": price, "change_pct": change_pct,
        "dims": [d.to_dict() for d in dims],
        "total": total, "verdict": verdict,
        "timing_notes": timing_notes,
        "highlights": highlights, "risks": risks,
    }


def build_doctor_report(data: dict) -> tuple[str, str]:
    """生成体检报告（HTML, Markdown）。"""
    as_of = data["as_of"]

    def _score_cell(d: dict) -> str:
        if d["score"] is None:
            return '<span style="color:#86909c">缺失</span>'
        s = d["score"]
        color = "#e02e24" if s >= 70 else ("#b7950b" if s >= 55 else "#00a870")
        return f'<span style="color:{color};font-weight:600">{s}</span>'

    tr = []
    md_rows = [
        "| 维度 | 评分 | 明细 |",
        "| --- | --- | --- |",
    ]
    for d in data["dims"]:
        sc = f"{d['score']}" if d["score"] is not None else "缺失"
        tr.append(
            "<tr>"
            f"<td>{d['label']}</td><td>{_score_cell(d)}</td>"
            f'<td style="text-align:left">{d["detail"]}</td>'
            "</tr>"
        )
        md_rows.append(f"| {d['label']} | {sc} | {d['detail']} |")

    hl_html = "".join(f"<li>{x}</li>" for x in data["highlights"])
    rk_html = "".join(f"<li>{x}</li>" for x in data["risks"])
    t_notes = "".join(f"<li>{x}</li>" for x in data["timing_notes"])
    verdict_color = {"强势": "#e02e24", "中性": "#b7950b", "谨慎": "#00a870"}.get(
        data["verdict"], "")
    total_html = (
        f'<span style="font-size:28px;color:{verdict_color};font-weight:700">'
        f'{data["total"]}</span>'
        f' <span style="color:{verdict_color}">{data["verdict"]}</span>'
        if data["total"] is not None else "<span>无法评分</span>"
    )
    price_html = "无行情"
    if data["price"]:
        price_html = f"现价 {data['price']:.2f}"
        if data["change_pct"] is not None:
            price_html += f"（{data['change_pct']:+.2f}%）"

    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1080px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 20px 0 8px; }
.meta { color: #86909c; font-size: 12px; margin-bottom: 16px; }
.score-box { background: #fff; border-radius: 8px; padding: 20px 24px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
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
<title>个股体检 {data['name']}({data['code']}) {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>个股全方位体检：{data['name']}（{data['code']}）</h1>
<div class="meta">{as_of} · 规则化评分（技术25%/基本面25%/筹码20%/资金15%/事件15%）· 涨红跌绿 ·
{price_html}</div>
<div class="score-box">综合评分 {total_html}
<div style="font-size:12px;color:#86909c;margin-top:6px">评分仅基于公开数据规则化计算，不构成投资建议。</div></div>
<h2>各维度明细</h2>
<div class="card"><table>
<tr><th>维度</th><th>评分</th><th style="text-align:left">明细</th></tr>
{''.join(tr)}
</table></div>
<h2>亮点</h2>
<div class="card"><ul>{hl_html if hl_html else '<li style="color:#86909c">暂无显著亮点</li>'}</ul></div>
<h2>风险提示</h2>
<div class="card"><ul>{rk_html if rk_html else '<li style="color:#86909c">暂无显著风险</li>'}</ul></div>
<h2>今日择时信号</h2>
<div class="card"><ul>{t_notes if t_notes else '<li style="color:#86909c">今日无买入信号</li>'}</ul></div>
<div class="footer">体检为规则化参考信息，不构成投资建议。市场有风险，投资需谨慎。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 个股体检 {data['name']}({data['code']}) {as_of}
date: {as_of}
tags: [体检, 评分]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 个股全方位体检：{data['name']}（{data['code']}）

综合评分：**{data['total']}（{data['verdict']}）**（技术25%/基本面25%/筹码20%/资金15%/事件15%）

## 各维度明细

{chr(10).join(md_rows)}

## 亮点

{chr(10).join(f"- {x}" for x in data['highlights']) if data['highlights'] else "- 暂无显著亮点"}

## 风险提示

{chr(10).join(f"- {x}" for x in data['risks']) if data['risks'] else "- 暂无显著风险"}

## 今日择时信号

{chr(10).join(f"- {x}" for x in data['timing_notes']) if data['timing_notes'] else "- 今日无买入信号"}

> 体检为规则化参考信息，不构成投资建议。
"""
    return html, md
