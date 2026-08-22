"""一键日报：聚合核心信号为一份"每日信号日报"。

聚合：行情快照 + 信号雷达总分 + 择时信号 + 未来 7 天事件 + 估值分位 +
研报数 + 增减持/回购公告 + 数据健康（K 线新鲜度）。
每个维度失败不阻塞，标注"缺失"。

声明：日报为公开数据聚合，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _freshness(rows: list[dict]) -> tuple[bool, str]:
    """K 线新鲜度：最近一根 vs 最近交易日。"""
    if not rows:
        return False, "无 K 线"
    last = rows[-1]["date"]
    gap = (datetime.now() - datetime.strptime(last, "%Y-%m-%d")).days
    if gap <= 3:
        return True, f"{last}（正常）"
    return False, f"{last}（落后 {gap} 天）"


def build_daily_data(cfg, codes: list[str] | None = None) -> dict:
    """采集日报数据。返回 {items: [每票聚合], health: [...]}。"""
    from .storage import load_klines

    from .corp_events import classify_event, EVENT_KEYWORDS
    from .radar import score_stock

    items = []
    health = []
    for it in cfg.watchlist:
        market = str(it.get("market", "ashare"))
        c = str(it["code"])
        if codes and c not in codes:
            continue
        name = str(it.get("name", c))
        rows = []
        try:
            if market == "crypto":
                # 币 K 线：Binance 直拉（open_time 为 int 毫秒时间戳）
                from datetime import datetime as _dt, timezone as _tz

                from .providers.binance import fetch_klines

                raw = fetch_klines(c, days=400)
                rows = [{
                    "date": _dt.fromtimestamp(int(k[0]) / 1000,
                                              tz=_tz.utc).strftime("%Y-%m-%d"),
                    "open": float(k[1]), "close": float(k[4]),
                    "high": float(k[2]), "low": float(k[3]),
                    "volume": float(k[5]),
                } for k in raw]
            else:
                rows = load_klines(c, market)
        except Exception:  # noqa: BLE001
            pass
        fresh, fnote = _freshness(rows)
        health.append(f"{name}({c}) K线: {fnote}")

        # 行情
        quote = {}
        if rows:
            last = rows[-1]
            prev = rows[-2]["close"] if len(rows) > 1 else last["close"]
            chg = (last["close"] / prev - 1) * 100 if prev else None
            quote = {"price": round(float(last["close"]), 2),
                     "change_pct": round(chg, 2) if chg is not None else None,
                     "date": last["date"]}

        # 信号雷达
        radar = None
        try:
            radar = score_stock(c, name, market, cfg=cfg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("日报雷达 %s 失败: %s", c, exc)

        # 择时
        timing = []
        try:
            from .timing import scan_timing

            timing = [f"{s.label}" for s in scan_timing(rows, c, name, market)]
        except Exception:  # noqa: BLE001
            pass

        # 事件（未来 7 天）
        events = []
        try:
            from .events import fetch_events

            events = [f"{e.kind} {e.date}" for e in fetch_events(c, market, days=7)]
        except Exception:  # noqa: BLE001
            pass

        # 估值分位
        valuation = None
        try:
            from .valuation import fetch_valuation

            if market == "ashare":
                v = fetch_valuation(c, years=5)
                if v:
                    valuation = (f"PE {v.pe_pct:.0f}% / PB {v.pb_pct:.0f}%"
                                 if v.pe_pct is not None and v.pb_pct is not None
                                 else "估值数据不足")
        except Exception:  # noqa: BLE001
            pass

        # 研报数
        ratings = 0
        try:
            from .announcements import fetch_research_reports

            if market == "ashare":
                ratings = len(fetch_research_reports(c, days=30, limit=5))
        except Exception:  # noqa: BLE001
            pass

        # 增减持/回购
        corp = []
        try:
            from .announcements import fetch_announcements

            for a in fetch_announcements(c, limit=30):
                cls = classify_event(a["title"])
                if cls:
                    corp.append(f"{cls[0]}:{a['date']}")
        except Exception:  # noqa: BLE001
            pass

        items.append({
            "code": c, "name": name, "market": market, "quote": quote,
            "radar": radar, "timing": timing, "events": events,
            "valuation": valuation, "ratings": ratings, "corp": corp,
        })
    return {"items": items, "health": health}


def build_daily_report(data: dict, as_of: str | None = None) -> tuple[str, str]:
    """生成日报（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    items = data["items"]

    def _vc(v: str) -> str:
        return {"偏多": "#e02e24", "偏空": "#00a870", "中性": "#b7950b"}.get(v, "")

    tr = []
    md_rows = [
        "| 标的 | 现价/涨跌 | 雷达 | 择时 | 事件 | 估值 | 研报 | 增减持 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
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
        timing = "、".join(x["timing"]) if x["timing"] else "-"
        events = "、".join(x["events"]) if x["events"] else "-"
        val = x["valuation"] or "-"
        corp = "、".join(x["corp"]) if x["corp"] else "-"
        tr.append(
            "<tr>"
            f"<td>{x['name']}({x['code']})</td>"
            f"<td>{price} {chg}</td>"
            f"<td>{radar_cell}</td>"
            f'<td style="text-align:left">{timing}</td>'
            f'<td style="text-align:left">{events}</td>'
            f'<td style="text-align:left">{val}</td>'
            f"<td>{x['ratings']}</td>"
            f'<td style="text-align:left">{corp}</td>'
            "</tr>"
        )
        md_rows.append(
            f"| {x['name']}({x['code']}) | {price} {chg} | "
            f"{r.total:+.1f} {r.verdict}" if r else "| - |"
            f" | {timing} | {events} | {val} | {x['ratings']} | {corp} |"
        )

    health_html = "".join(f"<li>{h}</li>" for h in data["health"])
    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px 16px; }
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
<title>每日信号日报 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>每日信号日报</h1>
<div class="meta">{as_of} · 行情/雷达/择时/事件/估值/研报/增减持 一键聚合 · 涨红跌绿</div>
<div class="card"><table>
<tr><th>标的</th><th>现价/涨跌</th><th>雷达</th><th style="text-align:left">择时</th><th style="text-align:left">事件</th><th style="text-align:left">估值</th><th>研报</th><th style="text-align:left">增减持</th></tr>
{''.join(tr) if tr else '<tr><td colspan="8" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<h2>数据健康</h2>
<div class="card"><ul style="font-size:13px;color:#86909c">{health_html}</ul></div>
<div class="footer">公开数据聚合，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 每日信号日报 {as_of}
date: {as_of}
tags: [日报, 信号]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 每日信号日报 {as_of}

{chr(10).join(md_rows) if md_rows else "无数据。"}

## 数据健康

{chr(10).join(f"- {h}" for h in data['health']) if data['health'] else "- 无"}

> 公开数据聚合，不构成投资建议。
"""
    return html, md
