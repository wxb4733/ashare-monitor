"""大股东视角：增持/减持决策框架。

核心问题不是"涨不涨"，而是：
1. 能不能减（合规闸门）：破净（PB<1）、财报敏感期（披露前 30 日）、破发（尽力而为）
2. 该不该增/减（信号打分）：估值分位/质押/基金态度/回购/经营

数据源：估值分位（valuation）、事件日历（events）、质押（pledge）、
基金持仓（buyer）、增减持回购（corp_events）、产销（sector）。
发行价/分红明细免费源在沙箱不稳 → 如实标注"数据源受限"。

倾向判定：合规通过 + 信号总分 ≥+2 → 增持倾向；≤-2 → 减持倾向；其余观望。
声明：规则化决策框架演示，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Gate:
    """合规闸门。"""
    name: str
    passed: bool | None       # True=通过 False=受限 None=数据缺失
    note: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "note": self.note}


@dataclass
class InsiderView:
    code: str
    name: str
    market: str
    gates: list[Gate] = field(default_factory=list)
    signals: list[tuple[str, float, str]] = field(default_factory=list)  # (标签, 分, 说明)
    total: float = 0.0
    verdict: str = "观望"       # 增持 / 减持 / 观望
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "market": self.market,
            "gates": [g.to_dict() for g in self.gates],
            "signals": self.signals, "total": self.total,
            "verdict": self.verdict, "issues": self.issues,
        }


def _verdict(total: float) -> str:
    return "增持" if total >= 2 else ("减持" if total <= -2 else "观望")


def analyze_insider(code: str, name: str, market: str, cfg=None) -> InsiderView:
    """大股东视角分析（A 股为主）。"""
    view = InsiderView(code=code, name=name, market=market)

    # ---- 合规闸门 ----
    # 1) 破净：PB < 1
    try:
        from .valuation import fetch_valuation

        v = fetch_valuation(code, years=5)
        if v is not None and v.pb_mrq is not None:
            if v.pb_mrq < 1:
                view.gates.append(Gate(
                    "破净检查", False, f"PB {v.pb_mrq:.2f} < 1，减持受限"))
            else:
                view.gates.append(Gate(
                    "破净检查", True, f"PB {v.pb_mrq:.2f} ≥ 1"))
    except Exception as exc:  # noqa: BLE001
        view.gates.append(Gate("破净检查", None, f"数据缺失：{exc}"))

    # 2) 财报敏感期：距下次披露 < 30 天
    try:
        from .events import fetch_events

        evs = fetch_events(code, market, days=40)
        report_days = [e for e in evs if "财报" in e.kind or "业绩" in e.kind]
        if report_days:
            from datetime import datetime as _dt

            d = _dt.strptime(report_days[0].date, "%Y-%m-%d")
            gap = (d - _dt.now()).days
            if gap < 30:
                view.gates.append(Gate(
                    "财报敏感期", False,
                    f"{report_days[0].kind} {report_days[0].date}（{gap} 天后），窗口期减持受限"))
            else:
                view.gates.append(Gate("财报敏感期", True,
                                       f"下次披露 {report_days[0].date}（{gap} 天后）"))
        else:
            view.gates.append(Gate("财报敏感期", True, "未来 40 天无财报披露"))
    except Exception as exc:  # noqa: BLE001
        view.gates.append(Gate("财报敏感期", None, f"数据缺失：{exc}"))

    # 3) 破发（尽力而为；发行价接口不稳 → 数据受限）
    try:
        issue_price = _fetch_issue_price(code)
        if issue_price is None:
            view.gates.append(Gate("破发检查", None, "发行价数据源受限"))
        else:
            price = v.close if v else None
            if price is not None and price < issue_price:
                view.gates.append(Gate("破发检查", False,
                                       f"现价 {price:.2f} < 发行价 {issue_price:.2f}"))
            else:
                view.gates.append(Gate("破发检查", True,
                                       f"现价 {price:.2f} ≥ 发行价 {issue_price:.2f}"))
    except Exception as exc:  # noqa: BLE001
        view.gates.append(Gate("破发检查", None, f"数据缺失：{exc}"))

    # ---- 信号打分 ----
    # 估值（低估→增持倾向；高估→减持倾向）
    if v is not None and v.pb_pct is not None:
        if v.pb_pct < 20:
            view.signals.append(("估值", 1.0, f"PB 分位 {v.pb_pct:.0f}% 低估"))
        elif v.pb_pct > 80:
            view.signals.append(("估值", -1.0, f"PB 分位 {v.pb_pct:.0f}% 高估"))
        else:
            view.signals.append(("估值", 0.0, f"PB 分位 {v.pb_pct:.0f}% 中性"))

    # 质押（高质押→减持压力/爆仓风险；单日快速检查，防网络挂起）
    try:
        from .pledge import fetch_pledges

        pledge_rows = []
        try:
            pledge_rows = fetch_pledges(
                datetime.now().strftime("%Y%m%d"))
        except Exception:  # noqa: BLE001
            pledge_rows = []
        hits = [r for r in pledge_rows if r.code == code]
        if hits:
            view.signals.append(("质押", -1.0, f"今日 {len(hits)} 笔质押公告"))
        else:
            view.signals.append(("质押", 0.0, "今日无质押公告"))
    except Exception:  # noqa: BLE001
        view.signals.append(("质押", 0.0, "质押数据缺失"))

    # 基金态度（外部机构）
    try:
        if cfg is not None:
            from .buyer import fetch_fund_holds

            holds = fetch_fund_holds(cfg, codes=[code])
            if holds and holds[0].change_ratio is not None:
                cr = holds[0].change_ratio
                s = 0.5 if cr > 0 else (-0.5 if cr < 0 else 0.0)
                view.signals.append(("基金", s,
                                     f"Q2 基金{holds[0].change} {cr:+.1f}%"))
    except Exception:  # noqa: BLE001
        pass

    # 回购/增减持公告
    try:
        from .announcements import fetch_announcements
        from .corp_events import classify_event

        score, notes = 0.0, []
        for a in fetch_announcements(code, limit=30):
            cls = classify_event(a["title"])
            if cls:
                etype, _ = cls
                if etype == "回购":
                    score = max(score + 1.0, 1.0)
                    notes.append("回购")
                elif etype == "增持":
                    score = max(score + 1.0, 1.0)
                    notes.append("增持")
                elif etype == "减持":
                    score = min(score - 1.0, -1.0)
                    notes.append("减持")
        if notes:
            view.signals.append(("增减持", score, "；".join(notes[:3])))
        else:
            view.signals.append(("增减持", 0.0, "近 30 天无增减持/回购公告"))
    except Exception:  # noqa: BLE001
        pass

    # 经营（产销增速）
    try:
        from .announcements import fetch_announcements as _fa
        from .sector import parse_sales, _fetch_body

        anns = [a for a in _fa(code, limit=30) if "产销快报" in a["title"]]
        sales = []
        for a in anns[:2]:
            s, _, _ = parse_sales(a["title"])
            if s is None and a.get("url"):
                s, _, _ = parse_sales(_fetch_body(a["url"]))
            if s is not None:
                sales.append(s)
        if len(sales) >= 2:
            chg = (sales[0] / sales[1] - 1) * 100
            view.signals.append(("经营", 0.5 if chg > 0 else -0.5,
                                 f"月度销量环比 {chg:+.1f}%"))
        else:
            view.signals.append(("经营", 0.0, "销量数据不足"))
    except Exception:  # noqa: BLE001
        pass

    view.total = round(sum(s for _, s, _ in view.signals), 1)
    view.verdict = _verdict(view.total)
    for g in view.gates:
        if g.passed is False:
            view.issues.append(f"{g.name}受限：{g.note}")
    return view


def _fetch_issue_price(code: str) -> float | None:
    """尽力获取 IPO 发行价（东财 F10；沙箱不稳 → None）。"""
    try:
        import requests

        resp = requests.get(
            "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageCompanySurvey",
            params={"code": ("SZ" if code.startswith(("00", "30")) else "SH") + code},
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": "https://emweb.securities.eastmoney.com/"},
            timeout=8,
        )
        data = resp.json()
        for k, v in data.items():
            if "ISSUE_PRICE" in k.upper():
                return float(v)
        return None
    except Exception:  # noqa: BLE001
        return None


def build_insider_report(views: list[InsiderView],
                         as_of: str | None = None) -> tuple[str, str]:
    """生成大股东视角报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _vc(v: str) -> str:
        return {"增持": "#e02e24", "减持": "#00a870", "观望": "#b7950b"}.get(v, "")

    tr = []
    md_rows = ["| 标的 | 总分 | 倾向 | 合规闸门 | 信号 |",
               "| --- | --- | --- | --- | --- |"]
    for x in views:
        gates = []
        for g in x.gates:
            mark = ("✓" if g.passed else "✗") if g.passed is not None else "?"
            gates.append(f"{mark}{g.name}")
        sigs = []
        for label, s, note in x.signals:
            mark = "+" if s > 0 else ("-" if s < 0 else "")
            sigs.append(f"{label}:{mark}{s:.1f}")
        color = _vc(x.verdict)
        gate_html = " ".join(f'<span style="color:{"#e02e24" if g.passed is False else "#00a870" if g.passed else "#86909c"}">'
                             f"{'✗' if g.passed is False else '✓' if g.passed else '?'}{g.name}</span>"
                             for g in x.gates)
        sig_html = " ".join(
            f'<span style="color:{"#e02e24" if s > 0 else "#00a870" if s < 0 else "#86909c"}">'
            f"{label}{'+' if s > 0 else ''}{s:.1f}</span>"
            for label, s, _ in x.signals)
        tr.append(
            "<tr>"
            f"<td>{x.name}({x.code})</td>"
            f'<td style="font-weight:600">{x.total:+.1f}</td>'
            f'<td><span style="color:{color};font-weight:600">{x.verdict}</span></td>'
            f'<td style="text-align:left;font-size:12px">{gate_html}</td>'
            f'<td style="text-align:left;font-size:12px">{sig_html}</td>'
            "</tr>"
        )
        md_rows.append(
            f"| {x.name}({x.code}) | {x.total:+.1f} | {x.verdict} | "
            f"{' '.join(gates)} | {' '.join(sigs)} |")

    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px 16px; }
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
<title>大股东视角 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>大股东视角：增持 or 减持？</h1>
<div class="meta">{as_of} · 合规闸门（破净/敏感期/破发）→ 信号打分 → 倾向 · 总分 ≥+2 增持 / ≤-2 减持</div>
<div class="card"><table>
<tr><th>标的</th><th>总分</th><th>倾向</th><th style="text-align:left">合规闸门</th><th style="text-align:left">信号</th></tr>
{''.join(tr) if tr else '<tr><td colspan="5" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<div class="footer">规则化决策框架演示（破发/分红数据源在部分环境受限），不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 大股东视角 {as_of}
date: {as_of}
tags: [大股东, 增减持, 合规]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 大股东视角 {as_of}

{chr(10).join(md_rows) if md_rows else "无数据。"}

> 规则化决策框架演示，不构成投资建议。
"""
    return html, md
