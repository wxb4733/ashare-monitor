"""技术指标计算单元测试（合成数据，验证已知形态）。"""

import pandas as pd
import pytest

from ashare_monitor.indicators import (
    boll,
    compute_indicators,
    kdj,
    macd,
    rsi,
)


def make_df(closes: list[float], highs=None, lows=None, volumes=None) -> pd.DataFrame:
    n = len(closes)
    highs = highs or [c * 1.01 for c in closes]
    lows = lows or [c * 0.99 for c in closes]
    volumes = volumes or [1000.0] * n
    rows = []
    prev = closes[0]
    for i, c in enumerate(closes):
        rows.append({
            "日期": f"2026-01-{i + 1:02d}",
            "开盘": prev,
            "收盘": c,
            "最高": highs[i],
            "最低": lows[i],
            "成交量": volumes[i],
            "涨跌幅": (c / prev - 1) * 100 if i else 0.0,
            "振幅": (highs[i] - lows[i]) / prev * 100,
        })
        prev = c
    return pd.DataFrame(rows)


def test_macd_golden_cross_up_trend():
    """先跌后涨 → 出现金叉状态（DIF > DEA）。"""
    closes = [100.0 * 0.99**i for i in range(30)] + [100.0 * 0.99**29 * 1.01**i for i in range(30)]
    m = macd(pd.Series(closes))
    assert m.dif > m.dea
    assert m.hist > 0
    assert m.trend == "金叉"
    assert m.last_cross_date is not None
    assert m.days_since_cross is not None and m.days_since_cross >= 0


def test_macd_death_cross_down_trend():
    """先涨后跌 → 出现死叉状态（DIF < DEA）。"""
    closes = [100.0 * 1.01**i for i in range(30)] + [100.0 * 1.01**29 * 0.99**i for i in range(30)]
    m = macd(pd.Series(closes))
    assert m.dif < m.dea
    assert m.hist < 0
    assert m.trend == "死叉"


def test_rsi_oversold_oversold():
    """逐根大跌 → RSI 超卖；逐根大涨 → 超买。"""
    down = [100.0 * 0.98**i for i in range(30)]  # 逐根下跌
    up = [100.0 * 1.02**i for i in range(30)]    # 逐根上涨
    r_down = rsi(pd.Series(down))
    assert r_down.value < 30 and r_down.level == "超卖"
    r_up = rsi(pd.Series(up))
    assert r_up.value > 70 and r_up.level == "超买"


def test_rsi_flat_is_50():
    r = rsi(pd.Series([100.0] * 30))
    assert r.value == pytest.approx(50.0, abs=5)


def test_kdj_golden_cross_and_level():
    df = make_df([100.0 * 1.005**i for i in range(40)])
    s = kdj(df["收盘"], df["最高"], df["最低"])
    assert s.k > s.d  # 上升趋势中 K > D
    assert s.trend == "金叉"
    assert 0 <= s.k <= 100 and 0 <= s.d <= 100


def test_boll_positions():
    closes = [100.0 + (i % 6) for i in range(30)]  # 有波动的序列，std > 0
    mid_price = float(pd.Series(closes).mean())
    # 价格在中轨附近
    s_mid = boll(pd.Series(closes), price=mid_price)
    assert s_mid.position in ("中上", "中下")
    # 价格远高于上轨 → 超上轨
    s_high = boll(pd.Series(closes), price=200.0)
    assert s_high.position == "超上轨"
    # 价格远低于下轨 → 超下轨
    s_low = boll(pd.Series(closes), price=50.0)
    assert s_low.position == "超下轨"
    # 上轨 > 中轨 > 下轨
    assert s_high.upper > s_high.mid > s_high.lower
    assert s_high.bandwidth > 0


def test_compute_indicators_full():
    df = make_df([100.0 * 1.004**i for i in range(80)])
    ir = compute_indicators(df, price=float(df["收盘"].iloc[-1]))
    assert ir.macd.trend in ("金叉", "死叉", "临界")
    assert ir.rsi.value > 0
    assert ir.kdj.k is not None
    assert ir.boll.position in ("超上轨", "中上", "中下", "超下轨")
    line = ir.summary_line()
    assert "MACD" in line and "RSI" in line and "KDJ" in line and "BOLL" in line


def test_compute_indicators_short_series():
    """短序列不应崩溃（各指标容错）。"""
    df = make_df([100.0, 101.0, 102.0])
    ir = compute_indicators(df)
    assert ir.boll.bandwidth >= 0 or pd.isna(ir.boll.bandwidth)
