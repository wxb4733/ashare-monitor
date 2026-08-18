"""技术指标计算模块（纯 pandas 实现，无 TA-Lib 依赖）。

覆盖：MACD（金叉/死叉）、RSI（超买/超卖）、KDJ、BOLL（布林带位置）。
所有计算函数接受 DataFrame（列：收盘/最高/最低/成交量），与网络请求解耦。

声明：指标为技术分析参考，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class MACDState:
    dif: float
    dea: float
    hist: float
    trend: str          # 金叉 / 死叉 / 临界
    last_cross_date: str | None  # 最近一次交叉日期
    days_since_cross: int | None


@dataclass
class RSIState:
    value: float
    level: str          # 超买 / 超卖 / 正常
    rsi6: float = 0.0
    rsi24: float = 0.0


@dataclass
class KDJState:
    k: float
    d: float
    j: float
    trend: str          # 金叉 / 死叉 / 临界
    level: str          # 超买 / 超卖 / 正常


@dataclass
class BOLLState:
    upper: float
    mid: float
    lower: float
    position: str       # 超上轨 / 上轨上方 / 中上 / 中下 / 下轨下方 / 超下轨
    bandwidth: float    # 带宽 %


@dataclass
class IndicatorReport:
    macd: MACDState
    rsi: RSIState
    kdj: KDJState
    boll: BOLLState
    price: float

    def summary_line(self) -> str:
        """一行指标摘要（用于预警画像等紧凑场景）。"""
        parts = [
            f"MACD{self.macd.trend}" + (
                f"({self.macd.days_since_cross}日前)" if self.macd.days_since_cross else ""
            ),
            f"RSI {self.rsi.value:.0f}",
            f"KDJ{self.kdj.trend}",
            f"BOLL{self.boll.position}",
        ]
        return " | ".join(parts)


# ---------- MACD ----------

def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9,
         dates: pd.Series | None = None) -> MACDState:
    """MACD：DIF = EMA(fast) - EMA(slow)，DEA = EMA(signal, DIF)，柱 = 2×(DIF-DEA)。"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2

    spread = dif - dea
    last = spread.iloc[-1]
    trend = "金叉" if last > 0 else ("死叉" if last < 0 else "临界")

    # 最近一次交叉：按位置定位并映射到日期
    last_cross, days_since = None, None
    if len(spread) >= 2:
        sign = (spread > 0).astype(int).diff()
        cross_pos = sign[sign != 0].index
        if len(cross_pos) > 0:
            pos = spread.index.get_loc(cross_pos[-1])
            if dates is not None and pos < len(dates):
                last_cross = str(pd.Timestamp(dates.iloc[pos]).date())
            else:
                last_cross = f"T-{len(spread) - 1 - pos}"
            days_since = len(spread) - 1 - pos

    return MACDState(
        dif=float(dif.iloc[-1]),
        dea=float(dea.iloc[-1]),
        hist=float(hist.iloc[-1]),
        trend=trend,
        last_cross_date=last_cross,
        days_since_cross=days_since,
    )


# ---------- RSI ----------

def _rsi(close: pd.Series, n: int) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean()
    # 纯涨（无亏损）→ 100；纯跌（无盈利）→ 0；完全平盘 → 50；正常 → 公式
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    both = (avg_gain > 0) & (avg_loss > 0)
    rsi = rsi.where(both, pd.NA)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    rsi = rsi.fillna(50.0)
    return float(rsi.iloc[-1])


def rsi(close: pd.Series, n: int = 14, overbuy: float = 70.0,
        oversell: float = 30.0) -> RSIState:
    value = _rsi(close, n)
    if value >= overbuy:
        level = "超买"
    elif value <= oversell:
        level = "超卖"
    else:
        level = "正常"
    return RSIState(
        value=round(value, 2),
        level=level,
        rsi6=round(_rsi(close, 6), 2),
        rsi24=round(_rsi(close, 24), 2),
    )


# ---------- KDJ ----------

def kdj(close: pd.Series, high: pd.Series, low: pd.Series,
        n: int = 9, overbuy: float = 80.0, oversell: float = 20.0) -> KDJState:
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, pd.NA) * 100
    rsv = rsv.fillna(50.0)
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    j = 3 * k - 2 * d

    spread = k - d
    last = spread.iloc[-1]
    trend = "金叉" if last > 0 else ("死叉" if last < 0 else "临界")
    j_last = float(j.iloc[-1])
    if j_last >= overbuy:
        level = "超买"
    elif j_last <= oversell:
        level = "超卖"
    else:
        level = "正常"
    return KDJState(
        k=float(k.iloc[-1]), d=float(d.iloc[-1]), j=j_last,
        trend=trend, level=level,
    )


# ---------- BOLL ----------

def boll(close: pd.Series, price: float, n: int = 20, k: float = 2.0) -> BOLLState:
    mid = close.rolling(n).mean()
    std = close.rolling(n).std()
    upper = mid + k * std
    lower = mid - k * std
    u, m, l = float(upper.iloc[-1]), float(mid.iloc[-1]), float(lower.iloc[-1])

    band_w = (u - l) / m * 100 if m else 0.0
    if price > u:
        position = "超上轨"
    elif price > m:
        position = "中上"
    elif price > l:
        position = "中下"
    else:
        position = "超下轨"
    return BOLLState(
        upper=u, mid=m, lower=l, position=position, bandwidth=round(band_w, 2),
    )


def compute_indicators(
    df: pd.DataFrame,
    price: float | None = None,
) -> IndicatorReport:
    """基于日线 DataFrame 计算全部指标。"""
    close = df["收盘"].astype(float)
    high = df["最高"].astype(float)
    low = df["最低"].astype(float)
    dates = df["日期"].astype(str) if "日期" in df.columns else None
    price = price if price is not None else float(close.iloc[-1])
    return IndicatorReport(
        macd=macd(close, dates=dates),
        rsi=rsi(close),
        kdj=kdj(close, high, low),
        boll=boll(close, price),
        price=price,
    )
