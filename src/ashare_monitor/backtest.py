"""持有期回测：某日买入一定金额，持有 N 个交易日后卖出，计算收益率。

数据源：优先使用已回填入库的日 K（klines 表，离线快速）；
未回填时自动现拉日线兜底（不入库）。

注意：按整手成交（A 股 100 股/手、港股按每手股数），未计佣金/税费，
结果仅为历史价格模拟，不构成投资建议。
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 默认每手股数（A 股 100；港股不同标的不同，比亚迪 01211 为 500）
_DEFAULT_LOT = {"ashare": 100, "hk": 500}


def _load_daily(code: str, market: str) -> list[dict]:
    """取日 K 序列（优先入库数据，缺失时现拉）。"""
    from .storage import load_klines

    rows = load_klines(code, market)
    if len(rows) >= 2:
        return rows
    logger.info("%s(%s) 库内无日 K，现拉日线兜底", code, market)
    from .analysis import fetch_history

    df, _ = fetch_history(code, days=300, adjust="qfq",
                          market=market, period="daily")
    return [
        {"date": str(r["日期"])[:10], "open": float(r["开盘"]),
         "close": float(r["收盘"]), "high": float(r["最高"]),
         "low": float(r["最低"]), "volume": float(r["成交量"])}
        for _, r in df.iterrows()
    ]


def backtest(
    code: str,
    market: str = "ashare",
    buy_date: str | None = None,
    amount: float = 100000.0,
    hold_days: list[int] | None = None,
    lot_size: int | None = None,
    rows: list[dict] | None = None,
) -> list[dict]:
    """执行持有期回测。

    :param rows: 日 K 序列（测试可注入），None 时按 code/market 获取
    :return: 每档持有期的回测结果 dict 列表
    """
    rows = rows if rows is not None else _load_daily(code, market)
    if len(rows) < 2:
        raise RuntimeError(f"{code} 日 K 数据不足（{len(rows)} 根）")

    lot = lot_size or _DEFAULT_LOT.get(market, 100)
    holds = hold_days or [60]

    # 买入日：首个日期 >= buy_date 的交易日；未指定取最后一天之前（保证有数据可卖）
    buy_date = buy_date or rows[-2]["date"]
    buy_idx = next(
        (i for i, r in enumerate(rows) if r["date"] >= buy_date),
        len(rows) - 2,
    )
    buy = rows[buy_idx]

    results = []
    for hd in sorted(holds):
        sell_idx = buy_idx + hd
        if sell_idx >= len(rows):
            results.append({
                "hold_days": hd, "status": "数据不足",
                "available": len(rows) - 1 - buy_idx,
                "buy_date": buy["date"], "buy_price": buy["close"],
            })
            continue
        sell = rows[sell_idx]

        shares = int(amount / buy["close"] / lot) * lot
        if shares <= 0:
            results.append({
                "hold_days": hd, "status": "金额不足一手",
                "buy_date": buy["date"], "buy_price": buy["close"],
                "lot": lot,
            })
            continue
        buy_amount = shares * buy["close"]
        sell_amount = shares * sell["close"]

        # 持有期最高/最低（含买入与卖出日）
        window = rows[buy_idx:sell_idx + 1]
        high = max(r["high"] for r in window)
        low = min(r["low"] for r in window)

        days_held = sell_idx - buy_idx
        span_days = (
            datetime.strptime(sell["date"], "%Y-%m-%d")
            - datetime.strptime(buy["date"], "%Y-%m-%d")
        ).days
        ret = (sell_amount / buy_amount - 1) * 100
        annualized = (
            ((sell_amount / buy_amount) ** (365 / span_days) - 1) * 100
            if span_days > 0 else 0.0
        )

        results.append({
            "hold_days": days_held,
            "status": "ok",
            "buy_date": buy["date"], "buy_price": buy["close"],
            "sell_date": sell["date"], "sell_price": sell["close"],
            "shares": shares, "lot": lot,
            "buy_amount": buy_amount, "sell_amount": sell_amount,
            "return_pct": round(ret, 2),
            "annualized_pct": round(annualized, 2),
            "high": high, "low": low,
            "span_days": span_days,
        })
    return results


def dca_backtest(
    code: str,
    market: str = "ashare",
    amount: float = 10000.0,
    months: int = 60,
    hold_days: int = 250,
    lot_size: int | None = None,
    rows: list[dict] | None = None,
) -> dict:
    """定投回测：每月首个交易日买入固定金额，持有 N 个交易日后卖出。

    逐笔独立计算收益率（不复利），统计分布。
    :param rows: 日 K 序列（测试可注入），None 时自动获取
    """
    rows = rows if rows is not None else _load_daily(code, market)
    if len(rows) < 2:
        raise RuntimeError(f"{code} 日 K 数据不足（{len(rows)} 根）")

    lot = lot_size or _DEFAULT_LOT.get(market, 100)

    # 每月首个交易日（按 YYYY-MM 分组取每组第一个）
    monthly_idx: list[int] = []
    seen: set[str] = set()
    for i, r in enumerate(rows):
        ym = r["date"][:7]
        if ym not in seen:
            seen.add(ym)
            monthly_idx.append(i)

    # 每笔：买 + 持有，卖出日需在数据范围内
    trades = []
    for buy_idx in monthly_idx:
        sell_idx = buy_idx + hold_days
        if sell_idx >= len(rows):
            continue
        buy, sell = rows[buy_idx], rows[sell_idx]
        # 前复权失真（负价/零价）跳过，避免复数与误导
        if buy["close"] <= 0 or sell["close"] <= 0:
            continue
        shares = int(amount / buy["close"] / lot) * lot
        if shares <= 0:
            continue
        buy_amt = shares * buy["close"]
        sell_amt = shares * sell["close"]
        span = (datetime.strptime(sell["date"], "%Y-%m-%d")
                - datetime.strptime(buy["date"], "%Y-%m-%d")).days
        ret = (sell_amt / buy_amt - 1) * 100
        trades.append({
            "buy_date": buy["date"], "buy_price": buy["close"],
            "sell_date": sell["date"], "sell_price": sell["close"],
            "return_pct": round(ret, 2),
            "annualized_pct": round(
                ((sell_amt / buy_amt) ** (365 / span) - 1) * 100
                if span > 0 and buy_amt > 0 else 0.0, 1
            ),
        })
        if len(trades) >= months:
            break

    if not trades:
        raise RuntimeError(
            f"{code} 无可完成交易的月份（持有 {hold_days} 日超出数据范围）"
        )

    rets = [t["return_pct"] for t in trades]
    wins = [r for r in rets if r > 0]
    return {
        "trades": len(trades),
        "period": f"{trades[-1]['buy_date']} ~ {trades[0]['buy_date']}",
        "avg_return_pct": round(sum(rets) / len(rets), 2),
        "median_return_pct": round(sorted(rets)[len(rets) // 2], 2),
        "win_rate_pct": round(len(wins) / len(rets) * 100, 1),
        "best_pct": max(rets),
        "worst_pct": min(rets),
        "avg_annualized_pct": round(
            sum(t["annualized_pct"] for t in trades) / len(trades), 1
        ),
        "detail": trades,
    }


def dca_compare(
    codes: list[str],
    amount: float = 10000.0,
    months: int = 60,
    hold_days: int = 250,
    rows_map: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """多标的定投对比：同参数跑 dca_backtest，汇总统计表。

    :param codes: 代码列表（市场按位数推断：5 位 → hk，6 位 → ashare）
    :param rows_map: 测试注入 {code: rows}
    """
    results = []
    for code in codes:
        market = "hk" if len(code) == 5 else "ashare"
        rows = rows_map.get(code) if rows_map else None
        try:
            r = dca_backtest(code, market, amount=amount, months=months,
                             hold_days=hold_days, rows=rows)
            results.append({
                "code": code, "market": market,
                "trades": r["trades"],
                "period": r["period"],
                "avg_return_pct": r["avg_return_pct"],
                "median_return_pct": r["median_return_pct"],
                "win_rate_pct": r["win_rate_pct"],
                "best_pct": r["best_pct"],
                "worst_pct": r["worst_pct"],
                "avg_annualized_pct": r["avg_annualized_pct"],
            })
        except Exception as exc:  # noqa: BLE001
            results.append({
                "code": code, "market": market, "error": str(exc),
            })
    return results


def backtest_chart_data(
    code: str,
    market: str = "ashare",
    buy_date: str | None = None,
    hold_days: int = 250,
    amount: float = 100000.0,
    rows: list[dict] | None = None,
) -> dict:
    """生成单笔回测的 K 线可视化数据（买卖点窗口）。

    :return: {"title", "dates", "kdata", "volumes", "buy", "sell", "return_pct"}
    """
    rows = rows if rows is not None else _load_daily(code, market)
    if len(rows) < 2:
        raise RuntimeError(f"{code} 日 K 数据不足")
    lot = _DEFAULT_LOT.get(market, 100)
    buy_date = buy_date or rows[-hold_days - 2]["date"]
    buy_idx = next(
        (i for i, r in enumerate(rows) if r["date"] >= buy_date),
        len(rows) - 2,
    )
    sell_idx = buy_idx + hold_days
    if sell_idx >= len(rows):
        raise RuntimeError(f"持有 {hold_days} 日超出数据范围（{buy_idx}->{sell_idx}/{len(rows)}）")
    buy, sell = rows[buy_idx], rows[sell_idx]
    shares = int(amount / buy["close"] / lot) * lot
    if shares <= 0:
        raise RuntimeError("金额不足一手")
    ret = (shares * sell["close"] / (shares * buy["close"]) - 1) * 100

    # 窗口：买入前 60 根 ~ 卖出后 5 根
    start = max(0, buy_idx - 60)
    end = min(len(rows), sell_idx + 5)
    window = rows[start:end]
    return {
        "title": f"{code}({market}) 回测 {buy['date']}@{buy['close']:.2f} → "
                 f"{sell['date']}@{sell['close']:.2f}（{hold_days} 交易日，{ret:+.2f}%）",
        "dates": [r["date"] for r in window],
        "kdata": [[round(r["open"], 2), round(r["close"], 2),
                   round(r["low"], 2), round(r["high"], 2)] for r in window],
        "volumes": [int(r["volume"]) for r in window],
        "buy": {"x": buy["date"], "y": round(buy["close"], 2)},
        "sell": {"x": sell["date"], "y": round(sell["close"], 2)},
        "return_pct": round(ret, 2),
    }

import json as _json

_BT_CSS = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1080px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
.meta { color: #86909c; font-size: 12px; margin-bottom: 16px; }
.card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.chart { width: 100%; height: 460px; }
.ret { font-size: 26px; font-weight: 700; }
.up { color: #e02e24; } .down { color: #00a870; }
.footer { color: #86909c; font-size: 12px; text-align: center; padding: 16px 0 8px; }
"""

_BT_JS = """
function renderBt(elId, opts) {
  var up = '#e02e24', down = '#00a870';
  var chart = echarts.init(document.getElementById(elId));
  chart.setOption({
    title: { text: opts.title, left: 8, textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { data: ['K线', '成交量'], top: 28 },
    grid: [
      { left: 60, right: 20, top: 60, height: '55%' },
      { left: 60, right: 20, top: '74%', height: '16%' }
    ],
    xAxis: [
      { type: 'category', data: opts.dates, gridIndex: 0, axisLabel: { rotate: 40, fontSize: 10 } },
      { type: 'category', data: opts.dates, gridIndex: 1, axisLabel: { show: false } }
    ],
    yAxis: [
      { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#f0f0f0' } } },
      { gridIndex: 1, splitLine: { show: false } }
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 40, end: 100 }],
    series: [
      {
        name: 'K线', type: 'candlestick', data: opts.kdata,
        itemStyle: { color: up, color0: down, borderColor: up, borderColor0: down },
        markPoint: {
          symbolSize: 14,
          data: [
            { name: '买', coord: [opts.buy.x, opts.buy.y], value: 'B', itemStyle: { color: up },
              label: { formatter: 'B 买', color: up, fontWeight: 'bold' } },
            { name: '卖', coord: [opts.sell.x, opts.sell.y], value: 'S', itemStyle: { color: down },
              label: { formatter: 'S 卖', color: down, fontWeight: 'bold' } }
          ]
        }
      },
      {
        name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: opts.volumes,
        itemStyle: { color: function (p) {
          return p.dataIndex >= opts.buyIdx && p.dataIndex <= opts.sellIdx ? up : '#d0d3d8';
        } }
      }
    ]
  });
}
"""


def build_backtest_html(data: dict) -> str:
    """生成回测可视化 HTML（K 线 + 买卖点标注）。"""
    ret = data["return_pct"]
    ret_class = "up" if ret > 0 else ("down" if ret < 0 else "")
    ret_text = f"{ret:+.2f}%"
    buy_idx = data["dates"].index(data["buy"]["x"])
    sell_idx = data["dates"].index(data["sell"]["x"])
    js_opts = {
        "title": data["title"],
        "dates": data["dates"],
        "kdata": data["kdata"],
        "volumes": data["volumes"],
        "buy": data["buy"],
        "sell": data["sell"],
        "buyIdx": buy_idx,
        "sellIdx": sell_idx,
    }
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{data['title']}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>{_BT_CSS}</style>
</head>
<body>
<div class="container">
<h1>持有期回测</h1>
<div class="meta">买入 {data['buy']['x']} @ {data['buy']['y']} → 卖出 {data['sell']['x']} @ {data['sell']['y']}</div>
<div class="card">
  <div>区间收益 <span class="ret {ret_class}">{ret_text}</span></div>
  <div class="chart" id="bt-chart"></div>
</div>
<div class="footer">基于公开行情数据的历史价格模拟，未计佣金与税费，不构成投资建议。</div>
</div>
<script>{_BT_JS}
renderBt("bt-chart", {_json.dumps(js_opts, ensure_ascii=False)});
</script>
</body>
</html>"""


def build_compare_report(
    results: list[dict],
    amount: float = 10000.0,
    hold_days: int = 250,
    months: int = 60,
    as_of: str | None = None,
) -> tuple[str, str]:
    """生成多标的定投对比报告（HTML, Markdown）。results 为 dca_compare 输出。"""
    from datetime import datetime as _dt

    as_of = as_of or _dt.now().strftime("%Y-%m-%d")

    def _fmt(v, suffix: str = "", nd: int = 1) -> str:
        return f"{v:.{nd}f}{suffix}" if v is not None else "-"

    def _cls(ret: float | None) -> str:
        if ret is None:
            return ""
        return "up" if ret > 0 else ("down" if ret < 0 else "")

    tr = []
    md_rows = [
        "| 标的 | 市场 | 笔数 | 区间 | 平均收益 | 中位数 | 胜率 | 最好 | 最差 | 平均年化 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        if "error" in r:
            tr.append(
                "<tr><td>{}</td><td>{}</td><td colspan=\"8\" "
                "style=\"text-align:left;color:#e02e24\">{}</td></tr>".format(
                    r["code"], r["market"], r["error"],
                )
            )
            md_rows.append(f"| {r['code']} | {r['market']} | - | - | - | - | - | - | - | - |（{r['error']}）|")
            continue
        style = ("red" if (r["win_rate_pct"] or 0) >= 60 else
                 ("green" if (r["win_rate_pct"] or 0) <= 40 else ""))
        win = f"{r['win_rate_pct']:.0f}%"
        win_cell = f'<span class="{style}">{win}</span>' if style else win
        tr.append(
            "<tr>"
            f"<td>{r['code']}</td><td>{r['market']}</td><td>{r['trades']}</td>"
            f"<td>{r['period']}</td>"
            f'<td class="{_cls(r["avg_return_pct"])}">{_fmt(r["avg_return_pct"], "%")}</td>'
            f'<td>{_fmt(r["median_return_pct"], "%")}</td>'
            f"<td>{win_cell}</td>"
            f'<td class="up">{_fmt(r["best_pct"], "%")}</td>'
            f'<td class="down">{_fmt(r["worst_pct"], "%")}</td>'
            f'<td>{_fmt(r["avg_annualized_pct"], "%")}</td>'
            "</tr>"
        )
        md_rows.append(
            f"| {r['code']} | {r['market']} | {r['trades']} | {r['period']} | "
            f"{_fmt(r['avg_return_pct'], '%')} | {_fmt(r['median_return_pct'], '%')} | "
            f"{r['win_rate_pct']:.0f}% | {_fmt(r['best_pct'], '%')} | "
            f"{_fmt(r['worst_pct'], '%')} | {_fmt(r['avg_annualized_pct'], '%')} |"
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
<title>多标的定投对比 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>多标的定投对比报告</h1>
<div class="meta">{as_of} · 每月首个交易日买入 {amount:,.0f} 元，持有 {hold_days} 个交易日卖出 ·
近 {months} 个月 · 数据来源：本地回填 K 线 · 涨红跌绿</div>
<div class="card"><table>
<tr><th>标的</th><th>市场</th><th>笔数</th><th>区间</th><th>平均收益</th><th>中位数</th><th>胜率</th><th>最好</th><th>最差</th><th>平均年化</th></tr>
{''.join(tr)}
</table></div>
<div class="footer">历史价格模拟，未计佣金税费，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 多标的定投对比 {as_of}
date: {as_of}
tags: [回测, 定投, 对比]
generated_at: {_dt.now():%Y-%m-%d %H:%M:%S}
---
# 多标的定投对比报告 {as_of}

每月首个交易日买入 {amount:,.0f} 元，持有 {hold_days} 个交易日卖出，近 {months} 个月。

{chr(10).join(md_rows)}

> 历史价格模拟，未计佣金税费，不构成投资建议。
"""
    return html, md
