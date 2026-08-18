"""规则化交易信号引擎单元测试（合成数据）。"""

import math
from datetime import datetime

import pandas as pd
import pytest

from ashare_monitor.analysis import TRADING_DAYS_PER_YEAR, HistoryReport, compute_metrics
from ashare_monitor.quotes import Quote
from ashare_monitor.signals import (
    DISCLAIMER,
    SignalConfig,
    generate_signals,
    make_verdict,
)


def make_df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    volumes = volumes or [1000.0] * n
    rows = []
    prev = closes[0]
    for i, c in enumerate(closes):
        high, low = c * 1.005, c * 0.995
        rows.append({
            "日期": f"2026-01-{i + 1:02d}",
            "开盘": prev,
            "收盘": c,
            "最高": high,
            "最低": low,
            "成交量": volumes[i],
            "涨跌幅": (c / prev - 1) * 100 if i else 0.0,
            "振幅": (high - low) / prev * 100,
        })
        prev = c
    return pd.DataFrame(rows)


def make_quote(price: float) -> Quote:
    return Quote(
        code="600519", name="测试股", price=price, change_pct=0.5,
        change=0.5, volume=1000, turnover=1e7, high=price + 1,
        low=price - 1, open=price, prev_close=price,
        timestamp=datetime(2026, 8, 18, 15, 0),
    )


def test_bullish_signals():
    # 稳定上行 + 近5日放量 → 多头信号占优
    closes = [100.0 * 1.005**i for i in range(70)]
    volumes = [1000.0] * 65 + [2000.0] * 5
    df = make_df(closes, volumes)
    report = compute_metrics(df)
    signals = generate_signals(report)
    scores = sum(s.score for s in signals)
    assert scores > 0
    names = {s.name for s in signals}
    assert "均线多头排列" in names and "站上MA20" in names and "放量" in names
    verdict = make_verdict(signals)
    assert verdict.direction == "偏多"
    assert 0 < verdict.confidence <= 1.0


def test_bearish_signals():
    # 稳定下行 + 放量 → 空头信号
    closes = [100.0 * 0.995**i for i in range(70)]
    volumes = [1000.0] * 65 + [2000.0] * 5
    df = make_df(closes, volumes)
    report = compute_metrics(df)
    signals = generate_signals(report)
    scores = sum(s.score for s in signals)
    assert scores < 0
    names = {s.name for s in signals}
    assert "均线空头排列" in names and "跌破MA20" in names
    assert make_verdict(signals).direction == "偏空"


def test_neutral_signal_flat_market():
    # 横盘震荡：无明确方向
    closes = [100.0 + (1 if i % 2 else -1) for i in range(70)]
    df = make_df(closes)
    report = compute_metrics(df)
    signals = generate_signals(report)
    assert any(s.direction == "neutral" for s in signals)
    assert make_verdict(signals).direction in ("中性", "偏多", "偏空")


def test_quote_price_affects_ma_signals():
    """实时价低于均线时，站上信号应转为跌破。"""
    closes = [100.0 * 1.003**i for i in range(70)]
    df = make_df(closes)
    report = compute_metrics(df)
    # 无 quote：以历史收盘判断 → 站上 MA20/MA60
    above = {s.name for s in generate_signals(report)}
    assert "站上MA20" in above and "站上MA60" in above
    # 模拟现价大幅跌破均线
    low_quote = make_quote(price=report.latest_close * 0.85)
    low = {s.name for s in generate_signals(report, low_quote)}
    assert "跌破MA20" in low and "跌破MA60" in low


def test_volatility_expansion_signal():
    """近20日波动放大 → 风险信号。"""
    # 前半段平稳，后半段剧烈波动
    closes = [100.0]
    for i in range(1, 60):
        if i < 40:
            closes.append(closes[-1] * 1.001)
        else:
            closes.append(closes[-1] * (1.03 if i % 2 else 0.97))
    df = make_df(closes)
    report = compute_metrics(df)
    signals = generate_signals(report)
    names = {s.name for s in signals}
    assert "波动放大" in names
    assert any(s.direction == "bearish" and s.name == "波动放大" for s in signals)


def test_momentum_signal():
    closes = [100.0 * 1.01**i for i in range(40)]   # 近20日动量明显为正
    df = make_df(closes)
    report = compute_metrics(df)
    signals = generate_signals(report)
    assert any(s.name == "动量向上" for s in signals)


def test_disclaimer_verbatim():
    assert DISCLAIMER.startswith("免责声明：以上内容基于公开数据和量化分析")
    assert "不构成投资建议" in DISCLAIMER
    assert "过往表现不预示未来收益" in DISCLAIMER


def test_custom_config_thresholds():
    closes = [100.0 * 1.005**i for i in range(70)]
    volumes = [1000.0] * 65 + [1200.0] * 5   # 量比 1.2 边缘
    df = make_df(closes, volumes)
    report = compute_metrics(df)
    strict = generate_signals(report, cfg=SignalConfig(volume_ratio_high=1.5))
    loose = generate_signals(report, cfg=SignalConfig(volume_ratio_high=1.1))
    assert not any(s.name == "放量" for s in strict)
    assert any(s.name == "放量" for s in loose)
