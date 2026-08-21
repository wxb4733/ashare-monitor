"""周期报告：日报 / 周报 / 月报，多视角（卖方/买方/大股东/雷达）同写。

数据层复用：daily.build_daily_data（行情/雷达/择时/事件/估值/研报/增减持）
+ buyer（预测修正/基金持仓）+ insider_view（大股东倾向）+ industry（行业月度）。

结构：每标的输出一行多视角摘要：
- 卖方视角：行业渗透率/厂商份额（industry）或产销（sector）
- 买方视角：预测方向/基金增减仓（buyer）
- 大股东视角：倾向（insider_view）
- 汇总裁决：雷达总分（daily）

声明：公开数据聚合，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _period_days(period: str) -> int:
    return {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 1)


def build_report_data(cfg, period: str = "daily",
                      codes: list[str] | None = None) -> dict:
    """采集周期报告数据（多视角聚合）。"""
    from .daily import build_daily_data

    data = build_daily_data(cfg, codes=codes)
    data["period"] = period
    data["days"] = _period_days(period)

    # 补充多视角
    for item in data["items"]:
        code, name, market = item["code"], item["name"], item["market"]
        # 买方：预测修正 + 基金持仓
        try:
            from .buyer import fetch_prediction, fetch_fund_holds

            pred = fetch_prediction(code, name)
            item["prediction"] = (f"{pred.direction} {pred.chg_pct:+.1f}%"
                                  if pred.chg_pct is not None else pred.direction)
            holds = fetch_fund_holds(cfg, codes=[code])
            if holds and holds[0].change_ratio is not None:
                item["fund_hold"] = (f"{holds[0].change} {holds[0].change_ratio:+.1f}%"
                                     f"（{holds[0].fund_count} 家）")
            else:
                item["fund_hold"] = "数据缺失"
        except Exception:  # noqa: BLE001
            item["prediction"] = "缺失"
            item["fund_hold"] = "缺失"
        # 大股东倾向
        try:
            from .insider_view import analyze_insider

            iv = analyze_insider(code, name, market, cfg=cfg)
            item["insider"] = f"{iv.total:+.1f} {iv.verdict}"
            item["insider_gates"] = [
                f"{'✗' if g.passed is False else '✓' if g.passed else '?'}{g.name}"
                for g in iv.gates]
        except Exception:  # noqa: BLE001
            item["insider"] = "缺失"
            item["insider_gates"] = []
        # 卖方：行业（月度渗透率/份额）
        item["industry"] = None
        if period in ("weekly", "monthly"):
            try:
                from .industry import fetch_industry

                ind = fetch_industry()
                pen = sorted(ind.penetration.items(),
                             key=lambda kv: kv[0])[-1] if ind.penetration else None
                byd = next((x for x in ind.man_rank
                            if x["name"] and "比亚迪" in x["name"]), None)
                item["industry"] = {
                    "penetration": f"{pen[1]:.1f}%({pen[0][:7]})"
                    if pen else "-",
                    "byd_rank": f"第{byd['rank']}名 {byd['cur']:.1f}万"
                    if byd else "-",
                }
            except Exception:  # noqa: BLE001
                item["industry"] = None
    return data


def build_period_report(data: dict, as_of: str | None = None) -> tuple[str, str]:
    """生成周期报告（HTML, Markdown）。"""
    period = data.get("period", "daily")
    title = {"daily": "日报", "weekly": "周报", "monthly": "月报"}.get(period, "报告")
    days = data.get("days", 1)
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    items = data["items"]

    def _vc(v: str) -> str:
        return {"偏多": "#e02e24", "偏空": "#00a870", "中性": "#b7950b",
                "增持": "#e02e24", "减持": "#00a870", "观望": "#b7950b"}.get(v, "")

    tr = []
    md_rows = [
        "| 标的 | 现价/涨跌 | 雷达 | 买方预期 | 基金持仓 | 大股东 | 卖方行业 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for x in items:
        q = x["quote"]
        price = f"{q['price']:.2f}" if q.get("price") else "-"
        chg = f"({q['change_pct']:+.2f}%)" if q.get("change_pct") is not None else ""
        r = x["radar"]
        radar_cell = "-"
        if r:
            radar_cell = (f'<span style="color:{_vc(r.verdict)};font-weight:600">'
                          f"{r.total:+.1f} {r.verdict}</span>")
        # 大股东倾向
        insider = x.get("insider", "缺失")
        ins_v = insider.split()[-1] if insider != "缺失" else "缺失"
        ins_cell = (f'<span style="color:{_vc(ins_v)};font-weight:600">'
                    f"{insider}</span>" if ins_v in ("增持", "减持", "观望")
                    else insider)
        ind = x.get("industry")
        ind_cell = (f"渗透率{ind['penetration']}｜比亚迪{ind['byd_rank']}"
                    if ind else "-")
        tr.append(
            "<tr>"
            f"<td>{x['name']}({x['code']})</td>"
            f"<td>{price} {chg}</td>"
            f"<td>{radar_cell}</td>"
            f"<td>{x.get('prediction', '-')}</td>"
            f"<td>{x.get('fund_hold', '-')}</td>"
            f"<td>{ins_cell}</td>"
            f'<td style="text-align:left">{ind_cell}</td>'
            "</tr>"
        )
        md_rows.append(
            f"| {x['name']}({x['code']}) | {price} {chg} | "
            f"{r.total:+.1f} {r.verdict}" if r else "| -"
            f" | {x.get('prediction', '-')} | {x.get('fund_hold', '-')} | "
            f"{insider} | {ind_cell} |"
        )

    # 事件区（周期内）
    ev_rows = []
    for x in items:
        evs = x.get("events") or []
        if evs:
            ev_rows.append(f"<tr><td>{x['name']}({x['code']})</td>"
                           f'<td style="text-align:left">{"、".join(evs)}</td></tr>')
    ev_html = "".join(ev_rows) if ev_rows else (
        '<tr><td colspan="2" style="text-align:center;color:#86909c">'
        f"本周期无重大事件</td></tr>")

    health_html = "".join(f"<li>{h}</li>" for h in data.get("health", []))

    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1300px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 20px 0 8px; }
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
<title>{title} {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>投资{title}（多视角）</h1>
<div class="meta">{as_of} · 近 {days} 天 · 卖方（行业/产销）· 买方（预期/基金）· 大股东（倾向）· 雷达（裁决）· 涨红跌绿</div>
<div class="card"><table>
<tr><th>标的</th><th>现价/涨跌</th><th>雷达</th><th>买方预期</th><th>基金持仓</th><th>大股东</th><th style="text-align:left">卖方行业</th></tr>
{''.join(tr) if tr else '<tr><td colspan="7" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<h2>本周期事件</h2>
<div class="card"><table>
<tr><th>标的</th><th style="text-align:left">事件</th></tr>
{ev_html}
</table></div>
<h2>数据健康</h2>
<div class="card"><ul style="font-size:13px;color:#86909c">{health_html}</ul></div>
<div class="footer">公开数据聚合，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: {title} {as_of}
date: {as_of}
tags: [{title}, 多视角]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 投资{title}（多视角）{as_of}

{chr(10).join(md_rows) if md_rows else "无数据。"}

## 本周期事件

{chr(10).join(f"- {x['name']}({x['code']})：{'、'.join(x.get('events') or ['无'])}" for x in items)}

## 数据健康

{chr(10).join(f"- {h}" for h in data.get('health', [])) if data.get('health') else "- 无"}

> 公开数据聚合，不构成投资建议。
"""
    return html, md
