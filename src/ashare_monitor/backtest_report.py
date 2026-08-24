"""回测 HTML 报告（backtesting.py/pyfolio 模式：净值曲线 + 月度热力图）。

纯标准库生成（无 matplotlib），输出 output/backtest-*.html：
    1. 统计对比表（组合 vs 静态 vs 基准，9 项指标）
    2. 净值曲线（SVG polyline：静态等权 / 再平衡 / 沪深 300）
    3. 月度收益热力图（年 × 月，红涨绿跌，中国习惯）

用法：
    from ashare_monitor.backtest_report import render_backtest_html
    render_backtest_html(result, codes, "output/backtest-2026-08-24.html")
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

# 月度收益着色（红涨绿跌，中国习惯；幅度分级）
_POS_COLORS = ["#FCEBEB", "#F7C1C1", "#F09595", "#E24B4A", "#A32D2D"]
_NEG_COLORS = ["#EAF3DE", "#C0DD97", "#97C459", "#639922", "#3B6D11"]


def _color_for(ret: float) -> str:
    """按幅度分级取色。"""
    if ret >= 0:
        idx = min(4, int(abs(ret) // 2))
        return _POS_COLORS[idx]
    idx = min(4, int(abs(ret) // 2))
    return _NEG_COLORS[idx]


def _monthly_returns(dates: list[str], nav_pcts: list[float]) -> dict:
    """从净值序列算月度收益：{year: {month: pct}}。"""
    out: dict[str, dict[int, float]] = {}
    prev_nav = 1.0
    prev_key = None
    for d, pct in zip(dates, nav_pcts):
        nav = 1 + pct / 100
        key = d[:7]
        if prev_key is not None and key != prev_key:
            # 上月末结算：本月收益 = 本月首日净值/上月末净值 - 1
            year, month = prev_key[:4], int(prev_key[5:7])
            out.setdefault(year, {})[month] = (nav / prev_nav - 1) * 100
            prev_nav = nav
        prev_key = key
    # 最后一个月结算
    if prev_key:
        year, month = prev_key[:4], int(prev_key[5:7])
        out.setdefault(year, {})[month] = 0.0
    return out


def _svg_nav_curve(dates: list[str], series: dict[str, list[float]]) -> str:
    """净值曲线 SVG（三条 polyline + 图例 + 坐标刻度）。"""
    w, h, pad_l, pad_b = 640, 300, 52, 26
    inner_w, inner_h = w - pad_l - 12, h - pad_b - 12
    all_vals = [v for vals in series.values() for v in vals if v is not None]
    if not all_vals:
        return "<svg viewBox='0 0 680 320'></svg>"
    lo, hi = min(all_vals), max(all_vals)
    span = (hi - lo) or 1.0
    n = len(dates)

    def _pt(vals, i, v):
        x = pad_l + i / (n - 1) * inner_w if n > 1 else pad_l
        y = 12 + inner_h - (v - lo) / span * inner_h
        return f"{x:.1f},{y:.1f}"

    colors = {"buy_hold": "#185FA5", "periodic": "#A32D2D",
              "benchmark": "#888780"}
    labels = {"buy_hold": "静态等权", "periodic": "再平衡", "benchmark": "沪深300"}
    parts = [f"<svg viewBox='0 0 {w} {h}' role='img' "
             "xmlns='http://www.w3.org/2000/svg'>"]
    # 网格 + 刻度（5 档）
    for k in range(6):
        v = lo + span * k / 5
        y = 12 + inner_h - k / 5 * inner_h
        parts.append(f"<line x1='{pad_l}' y1='{y:.1f}' x2='{w - 12}' "
                     f"y2='{y:.1f}' stroke='#00000022' stroke-width='0.5'/>")
        parts.append(f"<text x='{pad_l - 4}' y='{y + 3:.1f}' font-size='10' "
                     f"fill='#888' text-anchor='end'>{v:+.0f}%</text>")
    # 三条曲线
    for key in ("buy_hold", "periodic", "benchmark"):
        vals = series.get(key) or []
        pts = [_pt(vals, i, v) for i, v in enumerate(vals)
               if v is not None]
        if not pts:
            continue
        parts.append(f"<polyline points='{' '.join(pts)}' fill='none' "
                     f"stroke='{colors[key]}' stroke-width='1.6'/>")
    # 图例
    lx = pad_l + 8
    for key in ("periodic", "buy_hold", "benchmark"):
        parts.append(f"<line x1='{lx}' y1='{h - 8}' x2='{lx + 18}' "
                     f"y2='{h - 8}' stroke='{colors[key]}' stroke-width='2'/>")
        parts.append(f"<text x='{lx + 24}' y='{h - 5}' font-size='11' "
                     f"fill='#444'>{labels[key]}</text>")
        lx += 130
    # 首末日期
    parts.append(f"<text x='{pad_l}' y='{h - 5}' font-size='10' fill='#888' "
                 f"text-anchor='start'>{dates[0]}</text>")
    parts.append(f"<text x='{w - 12}' y='{h - 5}' font-size='10' fill='#888' "
                 f"text-anchor='end'>{dates[-1]}</text>")
    parts.append("</svg>")
    return "".join(parts)


def _monthly_heatmap(dates: list[str], nav_pcts: list[float]) -> str:
    """月度收益热力图 HTML（年 × 月，红涨绿跌）。"""
    mret = _monthly_returns(dates, nav_pcts)
    years = sorted(mret)
    rows = ["<table style='border-collapse:collapse;font-size:12px'>",
            "<tr><th style='padding:3px 8px'>年</th>"
            + "".join(f"<th style='padding:3px 6px'>{m}月</th>"
                      for m in range(1, 13)) + "</tr>"]
    for y in years:
        cells = []
        for m in range(1, 13):
            r = mret[y].get(m)
            if r is None:
                cells.append("<td style='padding:3px 6px;color:#bbb'>·</td>")
            else:
                color = _color_for(r)
                txt = f"{r:+.1f}"
                fg = "#501313" if r >= 0 else "#173404"
                cells.append(f"<td style='padding:3px 6px;background:{color};"
                             f"color:{fg};text-align:right;border:1px "
                             f"solid #00000011'>{txt}</td>")
        rows.append(f"<tr><td style='padding:3px 8px;font-weight:500'>{y}"
                    f"</td>{''.join(cells)}</tr>")
    rows.append("</table>")
    return "".join(rows)


def _stats_table(result: dict) -> str:
    """统计对比表（9 项指标 × 组合/静态/基准）。"""
    fields = [("total", "区间收益%"), ("annual", "年化%"),
              ("max_dd", "最大回撤%"), ("sharpe", "夏普"),
              ("sortino", "Sortino"), ("win_rate", "日胜率%"),
              ("profit_factor", "盈亏比"), ("best_day", "最佳日%"),
              ("worst_day", "最差日%")]
    rows = ["<table style='border-collapse:collapse;font-size:12px'>",
            "<tr><th style='padding:4px 10px;border:1px solid #ddd'>指标</th>"
            "<th style='padding:4px 10px;border:1px solid #ddd'>再平衡</th>"
            "<th style='padding:4px 10px;border:1px solid #ddd'>静态等权</th>"
            "<th style='padding:4px 10px;border:1px solid #ddd'>沪深300</th></tr>"]
    for key, label in fields:
        cells = [f"<td style='padding:4px 10px;border:1px solid #ddd'>"
                 f"{result['periodic'].get(key, '-')}</td>",
                 f"<td style='padding:4px 10px;border:1px solid #ddd'>"
                 f"{result['buy_hold_cost'].get(key, '-')}</td>",
                 f"<td style='padding:4px 10px;border:1px solid #ddd'>"
                 f"{result['benchmark'].get(key, '-')}</td>"]
        rows.append(f"<tr><td style='padding:4px 10px;border:1px solid #ddd'>"
                    f"{label}</td>{''.join(cells)}</tr>")
    rows.append("</table>")
    return "".join(rows)


def render_backtest_html(result: dict, codes: list[str],
                         path: str | Path) -> str:
    """渲染回测 HTML 报告，返回保存路径。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    nav = result.get("nav_series") or {}
    dates = nav.get("dates") or result["dates"]
    series = {k: nav.get(k) or [] for k in ("buy_hold", "periodic",
                                            "benchmark")}
    freq_label = {"monthly": "月度", "quarterly": "季度",
                  "semi_annual": "半年"}.get(result.get("frequency", ""),
                                             result.get("frequency", ""))
    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>回测报告 {dates[0]} ~ {dates[-1]}</title></head>
<body style="font-family:'Segoe UI',sans-serif;margin:24px;color:#222">
<h2 style="font-weight:500">组合回测报告（{'、'.join(codes)}）</h2>
<p style="color:#666;font-size:13px">
{freq_label}再平衡 · 单边成本 {result['cost_bps']}bp ·
涨跌停约束 {'开启（≥' + str(result.get('limit_pct')) + '%）' if result.get('limit_pct') else '关闭'} ·
{result['periodic']['days']} 个交易日 · 生成于 {datetime.now():%Y-%m-%d %H:%M}</p>
{_stats_table(result)}
<h3 style="font-weight:500">净值曲线（累计收益%）</h3>
{_svg_nav_curve(dates, series)}
<h3 style="font-weight:500">月度收益热力图（再平衡组合，%）</h3>
{_monthly_heatmap(dates, nav.get('periodic') or [])}
<p style="color:#999;font-size:11px">红涨绿跌（中国习惯）· 过往表现不预示未来收益</p>
</body></html>"""
    target.write_text(html, encoding="utf-8")
    return str(target)
