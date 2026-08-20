"""择时买入提醒：收盘后扫描自选股，识别技术性买点信号。

每个信号附带该规则在标的上全部历史信号（近 5 年）的方向命中率与平均收益
（复用本地回填 K 线计算，与 verify 口径一致），作为置信度参考。

信号规则：
- ma_pullback    强势回踩 MA20（均线向上 + 收盘贴近 20 日线未破位）
- deep_pullback  深度回调止跌（5 日跌超 8% 后当日企稳）
- macd_golden    MACD 金叉（DIF 上穿 DEA，优先低位）
- rsi_oversold   RSI 超卖回升（RSI14 上穿 30）
- volume_break   放量突破（量能 > 1.5×5日均量 且 收盘创 20 日新高）

仅基于本地回填 K 线，离线快速。声明：信号为统计提示，不构成投资建议。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

FORWARD = 5  # 置信度观察窗口（交易日）

# 规则定义
RULES: dict[str, dict] = {
    "ma_pullback": {
        "label": "强势回踩MA20",
        "desc": "20 日均线向上，收盘贴近 MA20（0.97~1.03 倍）未破位，多头趋势中的回踩买点",
    },
    "deep_pullback": {
        "label": "深度回调止跌",
        "desc": "5 个交易日跌超 8% 后当日止跌企稳，超跌反弹买点",
    },
    "macd_golden": {
        "label": "MACD金叉",
        "desc": "DIF 上穿 DEA 形成金叉（DIF 接近零轴，低位金叉更可靠）",
    },
    "rsi_oversold": {
        "label": "RSI超卖回升",
        "desc": "RSI14 从 30 以下回升上穿 30，超卖反转信号",
    },
    "volume_break": {
        "label": "放量突破",
        "desc": "成交量超过 5 日均量 1.5 倍且收盘创 20 日新高，资金进场突破",
    },
}


@dataclass
class TimingSignal:
    code: str
    name: str
    market: str
    rule: str
    label: str
    message: str
    win_rate: float | None = None      # 历史方向命中率 %
    avg_return: float | None = None    # 历史平均收益 %
    signals_count: int = 0             # 历史信号样本数
    signal_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "market": self.market,
            "rule": self.rule, "label": self.label, "message": self.message,
            "win_rate": self.win_rate, "avg_return": self.avg_return,
            "signals_count": self.signals_count, "signal_date": self.signal_date,
        }


def _series(rows: list[dict]) -> dict:
    """提取数值序列（日期升序）。"""
    return {
        "dates": [r["date"] for r in rows],
        "close": [float(r["close"]) for r in rows],
        "open": [float(r["open"]) for r in rows],
        "high": [float(r["high"]) for r in rows],
        "low": [float(r["low"]) for r in rows],
        "volume": [float(r["volume"]) for r in rows],
    }


def _sma(values: list[float], n: int, i: int) -> float | None:
    if i + 1 < n:
        return None
    return sum(values[i + 1 - n:i + 1]) / n


def _ema(values: list[float], n: int) -> list[float]:
    """EMA 序列（EWM span=n，adjust=False）。"""
    out: list[float] = []
    k = 2 / (n + 1)
    prev: float | None = None
    for v in values:
        if prev is None:
            prev = v
        else:
            prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def _rsi_series(closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * n
    gains, losses = 0.0, 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    for i in range(n, len(closes)):
        if i > n:
            d = closes[i] - closes[i - 1]
            gains = (gains * (n - 1) + max(d, 0)) / n
            losses = (losses * (n - 1) + max(-d, 0)) / n
        out.append(100.0 if losses == 0 else 100 - 100 / (1 + gains / losses))
    return out


def _history_signal_idxs(rows: list[dict], rule: str) -> list[int]:
    """扫描全部历史信号索引（日期升序）。"""
    s = _series(rows)
    closes, opens, highs, volumes = s["close"], s["open"], s["high"], s["volume"]
    n = len(closes)
    idxs: list[int] = []
    for i in range(26, n):
        hit = False
        if rule == "ma_pullback":
            ma_t = _sma(closes, 20, i)
            ma_p = _sma(closes, 20, i - 1)
            if ma_t and ma_p and ma_t > ma_p and ma_t > _sma(closes, 20, i - 2):
                hit = ma_t * 0.97 <= closes[i] <= ma_t * 1.03
        elif rule == "deep_pullback":
            base = closes[i - 5]
            if base and closes[i] / base - 1 < -0.08:
                hit = closes[i] > opens[i] or closes[i] > closes[i - 1]
        elif rule == "macd_golden":
            dif = _ema(closes, 12)
            dea = _ema(dif, 9)
            if i >= 1:
                hit = dif[i - 1] <= dea[i - 1] and dif[i] > dea[i]
        elif rule == "rsi_oversold":
            rsi_s = _rsi_series(closes)
            if rsi_s[i - 1] is not None:
                hit = rsi_s[i - 1] < 30 and rsi_s[i] is not None and rsi_s[i] > 30
        elif rule == "volume_break":
            if i >= 5:
                avg5 = sum(volumes[i - 5:i]) / 5
                prev_high = max(highs[i - 20:i])
                hit = (volumes[i] > 1.5 * avg5 and avg5 > 0
                       and closes[i] > prev_high)
        if hit:
            idxs.append(i)
    return idxs


def _confidence(rows: list[dict], idxs: list[int], forward: int = FORWARD) -> tuple:
    """统计历史信号触发后 forward 日收益：返回 (命中率%, 平均收益%, 样本数)。"""
    closes = [float(r["close"]) for r in rows]
    rets = []
    for i in idxs:
        j = i + forward
        if j < len(closes) and closes[i] > 0:
            rets.append((closes[j] / closes[i] - 1) * 100)
    if not rets:
        return None, None, 0
    wins = sum(1 for r in rets if r > 0)
    return round(wins / len(rets) * 100, 1), round(sum(rets) / len(rets), 2), len(rets)


def scan_timing(
    rows: list[dict], code: str, name: str, market: str,
    forward: int = FORWARD,
) -> list[TimingSignal]:
    """扫描标的当前（最后一根 K 线）是否出现买点信号。

    :param rows: load_klines 结果（升序，建议全量以得到更多历史样本）
    """
    if len(rows) < 60:
        return []
    today = rows[-1]["date"]
    signals: list[TimingSignal] = []
    for rule, spec in RULES.items():
        idxs = _history_signal_idxs(rows, rule)
        if not idxs or idxs[-1] != len(rows) - 1:
            continue  # 今日未触发
        win_rate, avg_return, cnt = _confidence(rows, idxs, forward)
        signals.append(TimingSignal(
            code=code, name=name, market=market, rule=rule,
            label=spec["label"], message=spec["desc"],
            win_rate=win_rate, avg_return=avg_return,
            signals_count=cnt, signal_date=today,
        ))
    return signals


def _load_watch_rows(code: str, market: str) -> list[dict]:
    from .storage import load_klines

    return load_klines(code, market)


# ---------- 报告 ----------

def build_timing_report(
    all_signals: list[TimingSignal], as_of: str | None = None,
) -> tuple[str, str]:
    """生成择时信号报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _fmt(v, suffix: str = "", nd: int = 1) -> str:
        return f"{v:.{nd}f}{suffix}" if v is not None else "-"

    def _cls(v: float | None) -> str:
        if v is None:
            return ""
        return "up" if v > 0 else ("down" if v < 0 else "")

    tr = []
    md_rows = [
        "| 标的 | 信号 | 说明 | 历史命中率 | 平均收益 | 样本数 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for sg in all_signals:
        style = ("red" if (sg.win_rate or 0) >= 55 else "")
        win = f"{sg.win_rate:.0f}%" if sg.win_rate is not None else "-"
        win_cell = f'<span class="{style}">{win}</span>' if style else win
        tr.append(
            "<tr>"
            f"<td>{sg.name}({sg.code})</td>"
            f'<td><span class="tag">{sg.label}</span></td>'
            f'<td style="text-align:left">{sg.message}</td>'
            f"<td>{win_cell}</td>"
            f'<td class="{_cls(sg.avg_return)}">{_fmt(sg.avg_return, "%")}</td>'
            f"<td>{sg.signals_count}</td>"
            "</tr>"
        )
        md_rows.append(
            f"| {sg.name}({sg.code}) | {sg.label} | {sg.message} | "
            f"{win} | {_fmt(sg.avg_return, '%')} | {sg.signals_count} |"
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
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; background: #e8f3ff; color: #1677ff; }
.up { color: #e02e24; } .down { color: #00a870; }
.footer { color: #86909c; font-size: 12px; text-align: center; padding: 16px 0 8px; }
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>择时买入提醒 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>择时买入提醒</h1>
<div class="meta">{as_of} · 收盘后扫描自选股 · 历史命中率 = 该信号在标的上近 5 年全部历史信号触发后
{ FORWARD } 个交易日收益为正的比例 · 数据来源：本地回填 K 线</div>
<div class="card"><table>
<tr><th>标的</th><th>信号</th><th>说明</th><th>历史命中率</th><th>平均收益</th><th>样本数</th></tr>
{''.join(tr) if tr else '<tr><td colspan="6" style="text-align:center;color:#86909c">今日无买入信号</td></tr>'}
</table></div>
<div class="footer">信号为历史统计提示，不构成投资建议。市场有风险，投资需谨慎。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 择时买入提醒 {as_of}
date: {as_of}
tags: [择时, 买入信号]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 择时买入提醒 {as_of}

收盘后扫描自选股。历史命中率 = 该信号在标的上近 5 年全部历史信号触发后
{ FORWARD } 个交易日收益为正的比例。

{chr(10).join(md_rows) if md_rows else "今日无买入信号。"}

> 信号为历史统计提示，不构成投资建议。
"""
    return html, md


def scan_watchlist(cfg, codes: list[str] | None = None,
                   forward: int = FORWARD) -> list[TimingSignal]:
    """扫描自选股（或指定代码）全部标的，返回所有触发信号。"""
    all_signals: list[TimingSignal] = []
    for item in cfg.watchlist:
        market = str(item.get("market", "ashare"))
        if market == "crypto":
            continue
        code = str(item["code"])
        if codes and code not in codes:
            continue
        name = str(item.get("name", code))
        try:
            rows = _load_watch_rows(code, market)
        except Exception as exc:  # noqa: BLE001
            logger.warning("择时扫描：%s 数据读取失败: %s", code, exc)
            continue
        try:
            all_signals.extend(scan_timing(rows, code, name, market, forward))
        except Exception as exc:  # noqa: BLE001
            logger.warning("择时扫描：%s 信号计算失败: %s", code, exc)
    return all_signals
