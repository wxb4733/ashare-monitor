"""买方基金经理视角：盈利预测修正 / 基金重仓 / 风险收益指标 / 组合相关性。

数据源：
- 盈利预测修正：东财研报 EPS 预测序列（复用 fetch_research_reports）
- 基金重仓：东财"基金持仓"季度报表（stock_report_fund_hold）
- 风险收益：本地 K 线计算（年化波动率/最大回撤/夏普）
- 组合相关性：本地 K 线收益相关系数矩阵

决策闭环：预期（预测修正）→ 资金（基金持仓）→ 风险（回撤/夏普）。
声明：规则化统计，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

RISK_FREE = 0.02  # 无风险利率（夏普计算用）


@dataclass
class FundHold:
    code: str
    name: str
    quarter: str
    fund_count: int           # 持有基金家数
    hold_shares: float | None # 持股总数（股）
    market_value: float | None  # 持股市值（元）
    change: str               # 增仓/减仓
    change_ratio: float | None  # 变动比例 %

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "quarter": self.quarter,
            "fund_count": self.fund_count, "hold_shares": self.hold_shares,
            "market_value": self.market_value, "change": self.change,
            "change_ratio": self.change_ratio,
        }


@dataclass
class Prediction:
    code: str
    name: str
    latest_eps: float | None
    avg_eps: float | None       # 区间平均预测
    direction: str              # 上修 / 下修 / 平稳
    chg_pct: float | None

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name,
            "latest_eps": self.latest_eps, "avg_eps": self.avg_eps,
            "direction": self.direction, "chg_pct": self.chg_pct,
        }


@dataclass
class RiskMetric:
    code: str
    name: str
    annual_vol: float | None    # 年化波动率 %
    max_drawdown: float | None  # 最大回撤 %
    sharpe: float | None
    n_days: int

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name,
            "annual_vol": self.annual_vol, "max_drawdown": self.max_drawdown,
            "sharpe": self.sharpe, "n_days": self.n_days,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- 基金重仓 ----------

def fetch_fund_holds(cfg, codes: list[str] | None = None) -> list[FundHold]:
    """查自选股最新季度基金持仓。"""
    import akshare as ak

    codes = set(codes) if codes else {str(it["code"]) for it in cfg.watchlist}
    quarter = _latest_quarter()
    try:
        df = ak.stock_report_fund_hold(symbol="基金持仓", date=quarter)
    except Exception as exc:  # noqa: BLE001
        logger.warning("基金持仓 %s 失败: %s", quarter, exc)
        return []
    if df is None or df.empty:
        return []
    hits = []
    for _, r in df.iterrows():
        code = str(r.get("股票代码") or "")
        if code not in codes:
            continue
        hits.append(FundHold(
            code=code, name=str(r.get("股票简称") or ""),
            quarter=quarter,
            fund_count=int(r.get("持有基金家数") or 0),
            hold_shares=_f(r.get("持股总数")),
            market_value=_f(r.get("持股市值")),
            change=str(r.get("持股变化") or ""),
            change_ratio=_f(r.get("持股变动比例")),
        ))
    return hits


def _latest_quarter() -> str:
    """最近已披露季报季度（当前 2026-08 → 2026-06-30）。"""
    now = datetime.now()
    if now.month >= 10:
        return f"{now.year}0930"
    if now.month >= 7:
        return f"{now.year}0630"
    if now.month >= 4:
        return f"{now.year}0331"
    return f"{now.year - 1}1231"


# ---------- 盈利预测修正 ----------

def fetch_prediction(code: str, name: str = "",
                     days: int = 120) -> Prediction:
    """研报 EPS 预测序列：最新 vs 区间平均 → 修正方向。"""
    from .announcements import fetch_research_reports

    try:
        reps = fetch_research_reports(code, days=days, limit=50)
    except Exception as exc:  # noqa: BLE001
        logger.warning("预测修正 %s 失败: %s", code, exc)
        return Prediction(code, name, None, None, "数据缺失", None)
    eps_list = [_f(r.get("eps_this_year")) for r in reps
                if _f(r.get("eps_this_year")) is not None]
    if not eps_list:
        return Prediction(code, name, None, None, "数据缺失", None)
    latest = eps_list[0]
    avg = statistics.mean(eps_list)
    chg = (latest / avg - 1) * 100 if avg else None
    if chg is None or abs(chg) < 2:
        direction = "平稳"
    else:
        direction = "上修" if chg > 0 else "下修"
    return Prediction(code, name, latest, round(avg, 2),
                      direction, round(chg, 1) if chg is not None else None)


# ---------- 风险收益 ----------

def risk_metrics(code: str, name: str = "", market: str = "ashare",
                 days: int = 250) -> RiskMetric:
    """本地 K 线风险收益：年化波动率/最大回撤/夏普。"""
    from .storage import load_klines

    try:
        rows = load_klines(code, market)
    except Exception as exc:  # noqa: BLE001
        logger.warning("风险指标 %s 失败: %s", code, exc)
        return RiskMetric(code, name, None, None, None, 0)
    closes = [float(r["close"]) for r in rows[-days:]]
    if len(closes) < 30:
        return RiskMetric(code, name, None, None, None, len(closes))
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    vol = statistics.pstdev(rets) * math.sqrt(250) * 100
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = max(mdd, (peak - c) / peak)
    mdd *= 100
    mean_r = statistics.mean(rets)
    sharpe = ((mean_r - RISK_FREE / 250) / statistics.pstdev(rets)
              * math.sqrt(250)) if statistics.pstdev(rets) else None
    return RiskMetric(code, name, round(vol, 1), round(mdd, 1),
                      round(sharpe, 2) if sharpe is not None else None,
                      len(closes))


def correlation_matrix(cfg) -> tuple[list[str], list[list[float]]]:
    """自选股收益相关系数矩阵（本地 K 线，按日期对齐近 120 日）。"""
    from .storage import load_klines

    names, ret_map = [], []
    for it in cfg.watchlist:
        if str(it.get("market", "ashare")) == "crypto":
            continue
        code = str(it["code"])
        try:
            rows = load_klines(code, str(it.get("market", "ashare")))
        except Exception:  # noqa: BLE001
            continue
        if len(rows) < 40:
            continue
        # date -> 日收益
        m = {}
        for i in range(1, len(rows)):
            d = str(rows[i]["date"])
            prev = float(rows[i - 1]["close"])
            if prev:
                m[d] = float(rows[i]["close"]) / prev - 1
        names.append(str(it.get("name", code)))
        ret_map.append(m)
    if len(ret_map) < 2:
        return names, []
    # 共同日期集合，取最近 120 个共同交易日
    common = sorted(set.intersection(*[set(m) for m in ret_map]))[-120:]
    if len(common) < 30:
        return names, []
    mat = []
    for i in range(len(ret_map)):
        row = []
        for j in range(len(ret_map)):
            if i == j:
                row.append(1.0)
                continue
            ai = [ret_map[i][d] for d in common]
            bj = [ret_map[j][d] for d in common]
            row.append(round(_corr(ai, bj), 2))
        mat.append(row)
    return names, mat


def _corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma, mb = statistics.mean(a), statistics.mean(b)
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((x - mb) ** 2 for x in b))
    if not va or not vb:
        return 0.0
    return cov / (va * vb)


# ---------- 报告 ----------

def build_buyer_report(preds: list[Prediction], holds: list[FundHold],
                       risks: list[RiskMetric], corr_names: list[str],
                       corr_mat: list[list[float]],
                       as_of: str | None = None) -> tuple[str, str]:
    """生成买方视角报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _dir_color(d: str) -> str:
        return {"上修": "#e02e24", "下修": "#00a870", "平稳": "#b7950b"}.get(d, "")

    # 预测修正表
    ptr = []
    pmd = ["| 标的 | 最新EPS | 平均EPS | 方向 | 变化 |",
           "| --- | --- | --- | --- | --- |"]
    for p in preds:
        c = _dir_color(p.direction)
        eps_c = (f"<td>{p.latest_eps:.2f}</td>"
                 if p.latest_eps is not None else "<td>-</td>")
        avg_c = (f"<td>{p.avg_eps:.2f}</td>"
                 if p.avg_eps is not None else "<td>-</td>")
        dir_c = f'<td><span style="color:{c}">{p.direction}</span></td>'
        chg_c = (f"<td>{p.chg_pct:+.1f}%</td>"
                 if p.chg_pct is not None else "<td>-</td>")
        ptr.append(f"<tr><td>{p.name}({p.code})</td>{eps_c}{avg_c}"
                   f"{dir_c}{chg_c}</tr>")
        eps_s = f"{p.latest_eps:.2f}" if p.latest_eps is not None else "-"
        avg_s = f"{p.avg_eps:.2f}" if p.avg_eps is not None else "-"
        chg_s = f"{p.chg_pct:+.1f}%" if p.chg_pct is not None else "-"
        pmd.append(f"| {p.name}({p.code}) | {eps_s} | {avg_s} | "
                   f"{p.direction} | {chg_s} |")

    # 基金持仓表
    ftr = []
    fmd = ["| 标的 | 季度 | 基金家数 | 持股(万股) | 变动 |",
           "| --- | --- | --- | --- | --- |"]
    for h in holds:
        chg_color = "#e02e24" if h.change == "增仓" else "#00a870"
        shares_c = (f"<td>{h.hold_shares / 1e4:.0f}</td>"
                    if h.hold_shares else "<td>-</td>")
        chg_c = (f'<td><span style="color:{chg_color}">{h.change} '
                 f'{h.change_ratio:+.1f}%</span></td>'
                 if h.change_ratio is not None else "<td>-</td>")
        ftr.append(f"<tr><td>{h.name}({h.code})</td><td>{h.quarter}</td>"
                   f"<td>{h.fund_count}</td>{shares_c}{chg_c}</tr>")
        shares_s = f"{h.hold_shares / 1e4:.0f}" if h.hold_shares else "-"
        chg_s = (f"{h.change} {h.change_ratio:+.1f}%"
                 if h.change_ratio is not None else "-")
        fmd.append(f"| {h.name}({h.code}) | {h.quarter} | {h.fund_count} | "
                   f"{shares_s} | {chg_s} |")

    # 风险收益表
    rtr = []
    rmd = ["| 标的 | 年化波动率 | 最大回撤 | 夏普 |",
           "| --- | --- | --- | --- |"]
    for r in risks:
        vol_c = (f"<td>{r.annual_vol:.1f}%</td>"
                 if r.annual_vol is not None else "<td>-</td>")
        mdd_c = (f"<td>{r.max_drawdown:.1f}%</td>"
                 if r.max_drawdown is not None else "<td>-</td>")
        sh_c = (f"<td>{r.sharpe:.2f}</td>"
                if r.sharpe is not None else "<td>-</td>")
        rtr.append(f"<tr><td>{r.name}({r.code})</td>{vol_c}{mdd_c}{sh_c}</tr>")
        vol_s = f"{r.annual_vol:.1f}%" if r.annual_vol is not None else "-"
        mdd_s = f"{r.max_drawdown:.1f}%" if r.max_drawdown is not None else "-"
        sh_s = f"{r.sharpe:.2f}" if r.sharpe is not None else "-"
        rmd.append(f"| {r.name}({r.code}) | {vol_s} | {mdd_s} | {sh_s} |")

    # 相关性矩阵
    ctr = []
    if corr_names and corr_mat:
        header = "<tr><th>标的</th>" + "".join(f"<th>{n[:4]}</th>"
                                               for n in corr_names) + "</tr>"
        body = []
        for i, n in enumerate(corr_names):
            cells = [f"<td>{n[:4]}</td>"]
            for j, v in enumerate(corr_mat[i]):
                color = ("#e02e24" if v > 0.5 else
                         ("#00a870" if v < 0 else "#86909c"))
                cells.append(f'<td><span style="color:{color}">{v:.2f}</span></td>')
            body.append("<tr>" + "".join(cells) + "</tr>")
        ctr = [header + "".join(body)]

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
<title>买方视角 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>买方基金经理视角：预期 · 资金 · 风险</h1>
<div class="meta">{as_of} · 预期（研报EPS修正）· 资金（基金重仓）· 风险（波动/回撤/夏普）· 相关性</div>
<h2>盈利预测修正（近 120 天研报）</h2>
<div class="card"><table>
<tr><th>标的</th><th>最新EPS</th><th>平均EPS</th><th>方向</th><th>变化</th></tr>
{''.join(ptr) if ptr else '<tr><td colspan="5" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<h2>公募基金重仓（最新季度）</h2>
<div class="card"><table>
<tr><th>标的</th><th>季度</th><th>基金家数</th><th>持股(万股)</th><th>变动</th></tr>
{''.join(ftr) if ftr else '<tr><td colspan="5" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<h2>风险收益（近 250 日）</h2>
<div class="card"><table>
<tr><th>标的</th><th>年化波动率</th><th>最大回撤</th><th>夏普</th></tr>
{''.join(rtr) if rtr else '<tr><td colspan="4" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<h2>组合相关性（近 120 日收益）</h2>
<div class="card"><table>
{''.join(ctr) if ctr else '<tr><td style="text-align:center;color:#86909c">标的不够，无法计算</td></tr>'}
</table></div>
<div class="footer">规则化统计（夏普无风险利率 2%），不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 买方视角 {as_of}
date: {as_of}
tags: [买方, 预测修正, 基金持仓, 风险]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 买方基金经理视角 {as_of}

## 盈利预测修正

{chr(10).join(pmd) if pmd else "无数据。"}

## 公募基金重仓

{chr(10).join(fmd) if fmd else "无数据。"}

## 风险收益

{chr(10).join(rmd) if rmd else "无数据。"}

> 规则化统计（夏普无风险利率 2%），不构成投资建议。
"""
    return html, md
