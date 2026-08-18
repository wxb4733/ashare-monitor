"""规则化交易信号引擎。

基于历史分析指标（均线排列、量能、波动、动量）生成多空信号与综合研判。

重要声明：本模块输出的是**规则信号，仅供参考，不构成投资建议**。
任何交易决策需结合个人风险承受能力独立判断（见 DISCLAIMER）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .analysis import HistoryReport
from .quotes import Quote

# 固定免责声明（金融合规红线，禁止改写/缩减）
DISCLAIMER = (
    "免责声明：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。"
    "市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和"
    "投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。"
)


@dataclass
class Signal:
    name: str          # 信号名
    direction: str     # bullish / bearish / neutral
    score: int         # +1 / -1 / 0
    detail: str


@dataclass
class SignalConfig:
    volume_ratio_high: float = 1.2   # 放量阈值
    volume_ratio_low: float = 0.8    # 缩量阈值
    momentum_window: int = 20        # 动量回看周期
    momentum_pct: float = 3.0        # 动量强弱阈值（%）


@dataclass
class Verdict:
    direction: str    # 偏多 / 中性 / 偏空
    score: int        # 多空净得分
    confidence: float # 置信度 0~1（得分绝对值 / 信号数）


def _price(report: HistoryReport, quote: Quote | None) -> float:
    return quote.price if quote else report.latest_close


def generate_signals(
    report: HistoryReport,
    quote: Quote | None = None,
    cfg: SignalConfig | None = None,
) -> list[Signal]:
    """基于分析报告（+可选实时行情）生成信号列表。"""
    cfg = cfg or SignalConfig()
    price = _price(report, quote)
    signals: list[Signal] = []
    ma = report.ma

    # 1. 均线多空排列（MA5/10/20）
    if all(n in ma for n in (5, 10, 20)):
        if ma[5] > ma[10] > ma[20]:
            signals.append(Signal(
                "均线多头排列", "bullish", +1,
                f"MA5({ma[5]:.2f}) > MA10({ma[10]:.2f}) > MA20({ma[20]:.2f})",
            ))
        elif ma[5] < ma[10] < ma[20]:
            signals.append(Signal(
                "均线空头排列", "bearish", -1,
                f"MA5({ma[5]:.2f}) < MA10({ma[10]:.2f}) < MA20({ma[20]:.2f})",
            ))
        else:
            signals.append(Signal(
                "均线纠缠", "neutral", 0,
                f"MA5({ma[5]:.2f}) / MA10({ma[10]:.2f}) / MA20({ma[20]:.2f}) 无明确方向",
            ))

    # 2. 价格相对中期/长期均线
    for n, label in ((20, "MA20"), (60, "MA60")):
        if n in ma:
            if price >= ma[n]:
                signals.append(Signal(
                    f"站上{label}", "bullish", +1,
                    f"现价 {price:.2f} ≥ {label} {ma[n]:.2f}",
                ))
            else:
                signals.append(Signal(
                    f"跌破{label}", "bearish", -1,
                    f"现价 {price:.2f} < {label} {ma[n]:.2f}",
                ))

    # 3. 量能（量比：近5日均量 / 近20日均量）
    vr = report.volume_ratio
    if vr is not None:
        if vr >= cfg.volume_ratio_high:
            signals.append(Signal("放量", "bullish", +1, f"量比 {vr:.2f}，量能放大"))
        elif vr <= cfg.volume_ratio_low:
            signals.append(Signal("缩量", "neutral", -1, f"量比 {vr:.2f}，量能萎缩"))
        else:
            signals.append(Signal("量能平稳", "neutral", 0, f"量比 {vr:.2f}"))

    # 4. 波动率变化（近20日 vs 全区间年化）
    if report.annual_volatility_pct > 0 and report.recent20_volatility_pct > 0:
        ratio = report.recent20_volatility_pct / report.annual_volatility_pct
        if ratio >= 1.2:
            signals.append(Signal(
                "波动放大", "bearish", -1,
                f"近20日波动 {report.recent20_volatility_pct:.1f}% "
                f"为年化 {report.annual_volatility_pct:.1f}% 的 {ratio:.1f} 倍，风险上升",
            ))
        elif ratio <= 0.8:
            signals.append(Signal(
                "波动收窄", "neutral", 0,
                f"近20日波动 {report.recent20_volatility_pct:.1f}% 明显收窄，"
                f"或临近变盘，注意方向选择",
            ))

    # 5. 近 N 日动量
    if report.daily_returns is not None and len(report.daily_returns) > 1:
        momentum = report.daily_returns.tail(cfg.momentum_window).sum() * 100
        if momentum >= cfg.momentum_pct:
            signals.append(Signal(
                "动量向上", "bullish", +1,
                f"近{cfg.momentum_window}日累计 {momentum:+.1f}%",
            ))
        elif momentum <= -cfg.momentum_pct:
            signals.append(Signal(
                "动量向下", "bearish", -1,
                f"近{cfg.momentum_window}日累计 {momentum:+.1f}%",
            ))

    return signals


def make_verdict(signals: list[Signal]) -> Verdict:
    """综合信号给出研判。"""
    if not signals:
        return Verdict("中性", 0, 0.0)
    score = sum(s.score for s in signals)
    if score > 0:
        direction = "偏多"
    elif score < 0:
        direction = "偏空"
    else:
        direction = "中性"
    return Verdict(direction, score, round(abs(score) / len(signals), 2))
