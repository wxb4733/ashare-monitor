"""信号聚合雷达：把多维度监控信号合成多空计分，一眼看偏多/偏空。

维度与计分（每维失败跳过，缺失不计分，如实标注）：
- 技术面（timing 信号）  : 有信号 +1
- 筹码（股东户数集中度）: 集中 +1 / 稳定 0 / 分散 -1
- 资金（主力净流入亿）  : >1 +1 / 0~1 +0.5 / -1~0 -0.5 / <-1 -1
- 估值（PE/PB 分位）    : 双低估 +1 / 单低估 +0.5 / 双高估 -1 / 单高估 -0.5
- 事件（未来 30 天）    : 解禁 -1 / 业绩预告 0 / 无事件 0
- 增减持（公告信号）    : 减持 -1 / 增持 +1 / 回购 +1
- 质押（近 7 天公告）   : 质押 -1 / 解除 +0.5
- 研报（近 30 天）      : ≥2 篇 +0.5 / 有 EPS 预测 +0.5
- 产销（销量环比）      : 增长 +0.5 / 下滑 -0.5
- 龙虎榜（近 10 天）    : 上榜净买 +0.5 / 净卖 -0.5

总分判定：≥+2 偏多 / ≤-2 偏空 / 其余中性。
声明：规则化信号汇总，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RadarSignal:
    key: str
    label: str
    score: float | None      # 该维得分，None=数据缺失
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label,
            "score": self.score, "detail": self.detail,
        }


@dataclass
class StockRadar:
    code: str
    name: str
    market: str
    total: float
    verdict: str          # 偏多 / 偏空 / 中性
    signals: list[RadarSignal] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # 缺失维度

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "market": self.market,
            "total": self.total, "verdict": self.verdict,
            "signals": [s.to_dict() for s in self.signals],
            "missing": self.missing,
        }


def _verdict(total: float) -> str:
    return "偏多" if total >= 2 else ("偏空" if total <= -2 else "中性")


def _technical_score(code: str, market: str, rows: list[dict]) -> RadarSignal:
    try:
        from .timing import scan_timing

        sigs = scan_timing(rows, code, code, market)
        if sigs:
            return RadarSignal("technical", "技术面", 1.0,
                               "触发 " + sigs[0].label)
        return RadarSignal("technical", "技术面", 0.0, "无买入信号")
    except Exception as exc:  # noqa: BLE001
        return RadarSignal("technical", "技术面", None, str(exc)[:40])


def _chip_score(code: str) -> RadarSignal:
    try:
        from .holders import concentration_status

        state, desc = concentration_status(code)
        if state is None:
            return RadarSignal("chip", "筹码", None, "无户数数据")
        score = {"集中": 1.0, "稳定": 0.0, "分散": -1.0}[state]
        return RadarSignal("chip", "筹码", score, f"{state}；{desc[:40]}")
    except Exception as exc:  # noqa: BLE001
        return RadarSignal("chip", "筹码", None, str(exc)[:40])


def _fundflow_score(code: str) -> RadarSignal:
    try:
        from .fundflow import fetch_fundflow, fetch_fundflow_ak

        try:
            f = fetch_fundflow(code, "ashare", "")
        except Exception:  # noqa: BLE001
            f = fetch_fundflow_ak(code)
        if f.main_net is None:
            return RadarSignal("fundflow", "资金", None, "无资金流")
        m = f.main_net
        score = 1.0 if m > 1 else (0.5 if m > 0 else (-0.5 if m > -1 else -1.0))
        return RadarSignal("fundflow", "资金", score, f"主力 {m:+.2f} 亿")
    except Exception as exc:  # noqa: BLE001
        return RadarSignal("fundflow", "资金", None, str(exc)[:40])


def _valuation_score(code: str) -> RadarSignal:
    try:
        from .valuation import fetch_valuation

        v = fetch_valuation(code, years=5)
        if v is None:
            return RadarSignal("valuation", "估值", None, "无数据")
        pe_low = (v.pe_pct is not None and v.pe_pct < 20)
        pe_high = (v.pe_pct is not None and v.pe_pct > 80)
        pb_low = (v.pb_pct is not None and v.pb_pct < 20)
        pb_high = (v.pb_pct is not None and v.pb_pct > 80)
        lows = sum([pe_low, pb_low])
        highs = sum([pe_high, pb_high])
        score = 1.0 if lows == 2 else (0.5 if lows == 1 else (
            -1.0 if highs == 2 else (-0.5 if highs == 1 else 0.0)))
        return RadarSignal(
            "valuation", "估值", score,
            f"PE分位 {v.pe_pct:.0f}% / PB分位 {v.pb_pct:.0f}%"
            if v.pe_pct is not None and v.pb_pct is not None else "数据不足",
        )
    except Exception as exc:  # noqa: BLE001
        return RadarSignal("valuation", "估值", None, str(exc)[:40])


def _event_score(code: str) -> RadarSignal:
    try:
        from .events import fetch_events

        evs = fetch_events(code, "ashare", days=30)
        if not evs:
            return RadarSignal("event", "事件", 0.0, "未来 30 天无事件")
        unlock = [e for e in evs if e.kind == "解禁"]
        if unlock:
            return RadarSignal("event", "事件", -1.0,
                               f"{unlock[0].date} 解禁")
        return RadarSignal("event", "事件", 0.0,
                           f"{len(evs)} 项事件（无解禁）")
    except Exception as exc:  # noqa: BLE001
        return RadarSignal("event", "事件", None, str(exc)[:40])


def _insider_score(code: str, cfg) -> RadarSignal:
    try:
        from .corp_events import classify_event
        from .announcements import fetch_announcements

        anns = fetch_announcements(code, limit=30)
        score = 0.0
        notes = []
        for a in anns:
            cls = classify_event(a["title"])
            if not cls:
                continue
            etype, _ = cls
            if etype == "减持":
                score = min(score - 1.0, -1.0)
                notes.append("减持")
            elif etype == "增持":
                score = max(score + 1.0, 1.0)
                notes.append("增持")
            elif etype == "回购":
                score = max(score + 1.0, 1.0)
                notes.append("回购")
        if not notes:
            return RadarSignal("insider", "增减持", 0.0, "近 30 天无信号")
        return RadarSignal("insider", "增减持", score, "；".join(notes[:3]))
    except Exception as exc:  # noqa: BLE001
        return RadarSignal("insider", "增减持", None, str(exc)[:40])


def _pledge_score(code: str) -> RadarSignal:
    try:
        from .pledge import fetch_pledges

        today = datetime.now().strftime("%Y%m%d")
        rows = []
        for i in range(7):
            from datetime import timedelta

            d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            try:
                rows.extend(fetch_pledges(d))
            except Exception:  # noqa: BLE001
                continue
        hits = [r for r in rows if r.code == code]
        if not hits:
            return RadarSignal("pledge", "质押", 0.0, "近 7 天无质押公告")
        return RadarSignal("pledge", "质押", -1.0,
                           f"{len(hits)} 笔质押公告")
    except Exception as exc:  # noqa: BLE001
        return RadarSignal("pledge", "质押", None, str(exc)[:40])


def _rating_score(code: str, cfg) -> RadarSignal:
    try:
        from .announcements import fetch_research_reports

        reps = fetch_research_reports(code, days=30, limit=5)
        if not reps:
            return RadarSignal("rating", "研报", 0.0, "近 30 天无研报")
        eps = any(r.get("eps_this_year") for r in reps)
        score = (0.5 if len(reps) >= 2 else 0.0) + (0.5 if eps else 0.0)
        orgs = ",".join(r.get("org", "") for r in reps[:3])
        return RadarSignal("rating", "研报", score,
                           f"{len(reps)} 篇（{orgs[:30]}）")
    except Exception as exc:  # noqa: BLE001
        return RadarSignal("rating", "研报", None, str(exc)[:40])


def _sector_score(code: str) -> RadarSignal:
    try:
        from .sector import parse_sales, _fetch_body
        from .announcements import fetch_announcements

        anns = [a for a in fetch_announcements(code, limit=30)
                if "产销快报" in a["title"]]
        if not anns:
            return RadarSignal("sector", "产销", 0.0, "近期无产销快报")
        sales = []
        for a in anns[:2]:
            s, _, _ = parse_sales(a["title"])
            if s is None and a.get("url"):
                s, _, _ = parse_sales(_fetch_body(a["url"]))
            if s is not None:
                sales.append(s)
        if len(sales) < 2:
            return RadarSignal("sector", "产销", 0.0, "销量数据不足")
        chg = (sales[0] / sales[1] - 1) * 100
        score = 0.5 if chg > 0 else -0.5
        return RadarSignal("sector", "产销", score, f"环比 {chg:+.1f}%")
    except Exception as exc:  # noqa: BLE001
        return RadarSignal("sector", "产销", None, str(exc)[:40])


def score_stock(code: str, name: str, market: str,
                cfg=None) -> StockRadar:
    """对单只股票聚合信号计分。"""
    from .storage import load_klines

    rows = []
    try:
        rows = load_klines(code, market)   # 按市场查本地 K 线（ashare/hk/us/crypto）
    except Exception:  # noqa: BLE001
        pass
    signals = [_technical_score(code, market, rows)]
    if market == "ashare":
        signals += [_chip_score(code), _fundflow_score(code),
                    _valuation_score(code), _event_score(code),
                    _insider_score(code, cfg), _pledge_score(code),
                    _rating_score(code, cfg), _sector_score(code)]
    total = 0.0
    missing = []
    for s in signals:
        if s.score is None:
            missing.append(s.label)
            continue
        total += s.score
    total = round(total, 1)
    return StockRadar(code=code, name=name, market=market,
                      total=total, verdict=_verdict(total),
                      signals=signals, missing=missing)


def scan_radar(cfg, codes: list[str] | None = None) -> list[StockRadar]:
    """扫描全部自选股（或指定代码）信号雷达。"""
    result = []
    for it in cfg.watchlist:
        if str(it.get("market", "ashare")) == "crypto":
            continue
        c = str(it["code"])
        if codes and c not in codes:
            continue
        name = str(it.get("name", c))
        try:
            result.append(score_stock(c, name, str(it.get("market", "ashare")),
                                      cfg=cfg))
        except Exception as exc:  # noqa: BLE001
            logger.warning("雷达 %s 失败: %s", c, exc)
    return result


def build_radar_report(radars: list[StockRadar],
                       as_of: str | None = None) -> tuple[str, str]:
    """生成信号雷达报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _vc(v: str) -> str:
        return {"偏多": "#e02e24", "偏空": "#00a870", "中性": "#b7950b"}.get(v, "")

    tr = []
    md_rows = [
        "| 标的 | 总分 | 判定 | 各维信号 |",
        "| --- | --- | --- | --- |",
    ]
    for r in radars:
        color = _vc(r.verdict)
        sig_cells = []
        for s in r.signals:
            if s.score is None:
                sig_cells.append(f"{s.label}:缺失")
            else:
                mark = "+" if s.score > 0 else ("-" if s.score < 0 else "")
                sig_cells.append(f"{s.label}:{mark}{s.score:.1f}")
        sig_html = " ".join(
            f'<span style="color:{"#e02e24" if "+" in x else ("#00a870" if "-" in x and "缺失" not in x else "#86909c")}">'
            f"{x}</span>" for x in sig_cells)
        tr.append(
            "<tr>"
            f"<td>{r.name}({r.code})</td>"
            f'<td style="font-weight:600">{r.total:+.1f}</td>'
            f'<td><span style="color:{color};font-weight:600">{r.verdict}</span></td>'
            f'<td style="text-align:left;font-size:12px">{sig_html}</td>'
            "</tr>"
        )
        md_rows.append(f"| {r.name}({r.code}) | {r.total:+.1f} | {r.verdict} | "
                       f"{' '.join(sig_cells)} |")

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
<title>信号聚合雷达 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>信号聚合雷达</h1>
<div class="meta">{as_of} · 技术/筹码/资金/估值/事件/增减持/质押/研报/产销 多空计分 · 总分 ≥+2 偏多(红) / ≤-2 偏空(绿)</div>
<div class="card"><table>
<tr><th>标的</th><th>总分</th><th>判定</th><th style="text-align:left">各维信号</th></tr>
{''.join(tr) if tr else '<tr><td colspan="4" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<div class="footer">规则化信号汇总，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 信号聚合雷达 {as_of}
date: {as_of}
tags: [雷达, 信号]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 信号聚合雷达 {as_of}

{chr(10).join(md_rows) if md_rows else "无数据。"}

> 规则化信号汇总，不构成投资建议。
"""
    return html, md
