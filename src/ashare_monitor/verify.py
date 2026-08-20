"""预警/信号命中率验证：基于回填 K 线对价格类规则做事后回测。

对每种规则（上破/下破/急涨/急跌/跌破均线），扫描历史全部信号点，
统计触发后 N 个交易日的收益分布与"方向命中率"——回答
"按这个信号买入/回避，历史上到底准不准"。

数据源：本地 klines 表（离线快速，需先 backfill --kline）。

声明：命中率为历史统计，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 规则定义：label 展示名，direction 表示"预期方向"（up 预期涨 / down 预期跌）
RULES: dict[str, dict] = {
    "up_break": {
        "label": "上破20日高", "direction": "up",
        "desc": "收盘价突破近 20 日最高价（追突破）",
    },
    "down_break": {
        "label": "下破20日低", "direction": "down",
        "desc": "收盘价跌破近 20 日最低价（破位）",
    },
    "pct_surge": {
        "label": "5日急涨>8%", "direction": "up",
        "desc": "5 个交易日累计涨幅超过 8%（追涨）",
    },
    "pct_plunge": {
        "label": "5日急跌>8%", "direction": "down",
        "desc": "5 个交易日累计跌幅超过 8%（抄底/回避）",
    },
    "ma20_break": {
        "label": "跌破MA20", "direction": "down",
        "desc": "收盘价跌破 20 日均线（短期转弱）",
    },
}


def scan_signals(rows: list[dict], rule: str, lookback: int = 20,
                 threshold: float = 8.0) -> list[int]:
    """扫描 K 线序列中的规则信号点（返回行索引列表，升序）。

    :param rows: load_klines 结果（日期升序，含 open/close/high/low）
    :param lookback: 突破/均线回看周期
    :param threshold: 涨跌幅规则阈值（%）
    """
    closes = [float(r["close"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    signals: list[int] = []
    start = 5 if rule in ("pct_surge", "pct_plunge") else lookback
    for i in range(start, len(rows)):
        c = closes[i]
        if rule == "up_break":
            prev_high = max(highs[i - lookback:i])
            if c > prev_high:
                signals.append(i)
        elif rule == "down_break":
            prev_low = min(lows[i - lookback:i])
            if c < prev_low:
                signals.append(i)
        elif rule == "pct_surge":
            base = closes[i - 5]
            if base and (c / base - 1) * 100 > threshold:
                signals.append(i)
        elif rule == "pct_plunge":
            base = closes[i - 5]
            if base and (c / base - 1) * 100 < -threshold:
                signals.append(i)
        elif rule == "ma20_break":
            ma20 = sum(closes[i - 20:i]) / 20
            if c < ma20 and closes[i - 1] >= sum(closes[i - 21:i - 1]) / 20:
                signals.append(i)
    return signals


def verify_rule(rows: list[dict], rule: str, forward: int = 5,
                lookback: int = 20, threshold: float = 8.0,
                max_signals: int = 500) -> dict:
    """对单个规则做命中率验证。

    :param forward: 触发后观察 N 个交易日
    :return: {rule, label, desc, direction, signals, win_rate, avg_return,
              median_return, best, worst, forward, detail}
    """
    spec = RULES[rule]
    idxs = scan_signals(rows, rule, lookback, threshold)[-max_signals:]
    trades = []
    for i in idxs:
        j = i + forward
        if j >= len(rows):
            continue
        buy = float(rows[i]["close"])
        sell = float(rows[j]["close"])
        if buy <= 0:
            continue
        trades.append({
            "signal_date": rows[i]["date"],
            "close": round(buy, 2),
            "forward_return_pct": round((sell / buy - 1) * 100, 2),
        })
    if not trades:
        return {
            "rule": rule, "label": spec["label"], "desc": spec["desc"],
            "direction": spec["direction"], "signals": 0, "win_rate": None,
            "avg_return": None, "median_return": None,
            "best": None, "worst": None, "forward": forward, "detail": [],
        }
    rets = [t["forward_return_pct"] for t in trades]
    direction = spec["direction"]
    wins = sum(
        1 for r in rets if (r > 0 if direction == "up" else r < 0)
    )
    return {
        "rule": rule, "label": spec["label"], "desc": spec["desc"],
        "direction": direction,
        "signals": len(trades),
        "win_rate": round(wins / len(trades) * 100, 1),
        "avg_return": round(sum(rets) / len(rets), 2),
        "median_return": round(sorted(rets)[len(rets) // 2], 2),
        "best": max(rets), "worst": min(rets),
        "forward": forward, "detail": trades,
    }


def verify_all(rows: list[dict], forward: int = 5, days: int | None = None,
               max_signals: int = 500) -> list[dict]:
    """对全部规则跑命中率验证（返回规则结果列表）。"""
    if days:
        rows = rows[-days:]
    return [
        verify_rule(rows, rule, forward=forward, max_signals=max_signals)
        for rule in RULES
    ]


def _load_daily(code: str, market: str) -> list[dict]:
    from .storage import load_klines

    rows = load_klines(code, market)
    if len(rows) < 2:
        raise RuntimeError(f"{code} 本地 K 线不足，请先 backfill --kline")
    return rows


def build_verify_report(
    code: str, market: str, results: list[dict], as_of: str | None = None,
) -> tuple[str, str]:
    """生成命中率验证报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    forward = results[0]["forward"] if results else 5

    def _fmt(v, suffix: str = "", nd: int = 2) -> str:
        return f"{v:.{nd}f}{suffix}" if v is not None else "-"

    def _cls(ret: float | None) -> str:
        if ret is None:
            return ""
        return "up" if ret > 0 else ("down" if ret < 0 else "")

    # 汇总表
    tr = []
    md_rows = ["| 规则 | 信号数 | 方向命中率 | 平均收益 | 中位数 | 最好 | 最差 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        style = (
            "red" if (r["win_rate"] or 0) >= 60 else
            ("green" if (r["win_rate"] or 0) <= 40 else "")
        )
        win_cell = (
            f'<span class="{style}">{_fmt(r["win_rate"], "%", 1)}</span>'
            if style and r["win_rate"] is not None else _fmt(r["win_rate"], "%", 1)
        )
        tr.append(
            "<tr>"
            f"<td>{r['label']}</td><td>{r['signals']}</td><td>{win_cell}</td>"
            f'<td class="{_cls(r["avg_return"])}">{_fmt(r["avg_return"], "%")}</td>'
            f'<td>{_fmt(r["median_return"], "%")}</td>'
            f'<td class="up">{_fmt(r["best"], "%")}</td>'
            f'<td class="down">{_fmt(r["worst"], "%")}</td>'
            "</tr>"
        )
        md_rows.append(
            f"| {r['label']} | {r['signals']} | {_fmt(r['win_rate'], '%', 1)} | "
            f"{_fmt(r['avg_return'], '%')} | {_fmt(r['median_return'], '%')} | "
            f"{_fmt(r['best'], '%')} | {_fmt(r['worst'], '%')} |"
        )

    # 明细
    detail_tr = []
    for r in results:
        for t in r["detail"][-20:]:  # 每个规则最近 20 个信号
            cls = _cls(t["forward_return_pct"])
            detail_tr.append(
                "<tr>"
                f"<td>{r['label']}</td><td>{t['signal_date']}</td>"
                f"<td>{t['close']:.2f}</td>"
                f'<td class="{cls}">{t["forward_return_pct"]:+.2f}%</td>'
                "</tr>"
            )
    detail_html = f"""
<div class="card"><table>
<tr><th>规则</th><th>信号日</th><th>触发收盘价</th><th>后{forward}日收益</th></tr>
{''.join(detail_tr) if detail_tr else '<tr><td colspan="4" style="text-align:center;color:#86909c">无信号样本</td></tr>'}
</table></div>"""

    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1080px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 24px 0 8px; }
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
<title>信号命中率验证 {code} {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>信号命中率验证：{code}（{market}）</h1>
<div class="meta">{as_of} · 触发后观察 {forward} 个交易日 · 数据来源：本地回填 K 线 · 涨红跌绿</div>
<h2>规则命中率汇总（方向命中率 = 预期方向兑现比例）</h2>
<div class="card"><table>
<tr><th>规则</th><th>信号数</th><th>方向命中率</th><th>平均收益</th><th>中位数</th><th>最好</th><th>最差</th></tr>
{''.join(tr)}
</table></div>
<h2>信号明细（每个规则最近 20 个信号）</h2>
{detail_html}
<div class="footer">基于公开历史行情数据的统计回测，未计佣金税费，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 信号命中率验证 {code} {as_of}
date: {as_of}
tags: [回测, 命中率, 验证]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 信号命中率验证：{code}（{market}）

触发后观察 {forward} 个交易日。方向命中率 = 预期方向兑现比例（如"上破20日高"预期涨，命中 = 后续收益为正）。

## 规则命中率汇总

{chr(10).join(md_rows)}

## 信号明细（每个规则最近 20 个信号）

| 规则 | 信号日 | 触发收盘价 | 后{forward}日收益 |
| --- | --- | --- | --- |
{''.join(f"| {r['label']} | {t['signal_date']} | {t['close']:.2f} | {t['forward_return_pct']:+.2f}% |" for r in results for t in r['detail'][-20:])}

> 基于公开历史行情数据的统计回测，未计佣金税费，不构成投资建议。
"""
    return html, md


def run_verify(code: str, market: str, rule: str | None, days: int,
               forward: int) -> list[dict]:
    """命令行入口：加载数据并跑验证。"""
    rows = _load_daily(code, market)
    if rule:
        if rule not in RULES:
            raise RuntimeError(f"未知规则 {rule}，可选：{', '.join(RULES)}")
        return [verify_rule(rows, rule, forward=forward)]
    return verify_all(rows, forward=forward, days=days)
