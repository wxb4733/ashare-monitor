"""历史数据分析单元测试（合成数据，不依赖网络）。"""

import math

import pandas as pd
import pytest

from ashare_monitor.analysis import (
    TRADING_DAYS_PER_YEAR,
    ProfileCache,
    _parse_tencent_kline,
    brief_profile,
    compute_metrics,
)


def make_df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    """按收盘价序列构造 akshare 风格的日线 DataFrame。"""
    n = len(closes)
    volumes = volumes or [1000.0] * n
    rows = []
    prev = closes[0]
    for i, c in enumerate(closes):
        high, low = c * 1.01, c * 0.99
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


def test_compute_metrics_basic():
    df = make_df([100.0, 110.0, 99.0, 105.0])
    r = compute_metrics(df, code="000001", name="测试股")
    assert r.bars == 4
    assert r.latest_close == 105.0
    assert r.period_return_pct == pytest.approx(5.0)      # 100 → 105
    assert r.up_days == 2 and r.down_days == 1
    assert r.win_rate == pytest.approx(2 / 3 * 100)
    assert r.start_date == "2026-01-01"


def test_max_drawdown():
    # 100 → 120 → 90：峰值 120，谷底 90，回撤 -25%
    df = make_df([100.0, 120.0, 90.0, 95.0])
    r = compute_metrics(df)
    assert r.max_drawdown_pct == pytest.approx(-25.0)


def test_annual_volatility_constant_growth_is_zero():
    # 每日固定 +1% 复利，日收益标准差为 0，波动率为 0
    closes = [100.0 * 1.01**i for i in range(30)]
    df = make_df(closes)
    r = compute_metrics(df)
    assert r.annual_volatility_pct == pytest.approx(0.0, abs=1e-6)


def test_annual_volatility_alternating():
    # 每日 ±2% 交替，日收益标准差 ≈ 2%，年化 ≈ 2% × √250
    closes = [100.0]
    for i in range(1, 41):
        closes.append(closes[-1] * (1.02 if i % 2 else 1 / 1.02))
    df = make_df(closes)
    r = compute_metrics(df)
    expected = 2.0 * math.sqrt(TRADING_DAYS_PER_YEAR)
    assert r.annual_volatility_pct == pytest.approx(expected, rel=0.05)
    # 加密货币口径：√365 年化
    r365 = compute_metrics(df, periods_per_year=365)
    assert r365.annual_volatility_pct == pytest.approx(2.0 * math.sqrt(365), rel=0.05)


def test_amplitude_fallback_without_column():
    df = make_df([100.0, 101.0])
    df = df.drop(columns=["振幅"])
    r = compute_metrics(df)
    # 每根 (高-低)/昨收 = 100*1.01-100*0.99 = 2 → 2%
    assert r.avg_amplitude_pct == pytest.approx(2.0, abs=0.05)


def test_ma_and_volume_ratio():
    closes = [100.0 + i for i in range(70)]       # 稳定上行
    volumes = [1000.0] * 65 + [2000.0] * 5        # 近 5 日放量
    df = make_df(closes, volumes)
    r = compute_metrics(df)
    assert set(r.ma.keys()) == {5, 10, 20, 60}
    assert r.latest_close > r.ma[60]              # 收盘在长期均线上方
    assert r.volume_ma5 == 2000.0
    assert r.volume_ratio == pytest.approx(2000.0 / r.volume_ma20)
    assert r.volume_ratio > 1                     # 近期放量


def test_short_series_fewer_ma():
    df = make_df([100.0, 101.0, 102.0])
    r = compute_metrics(df)
    assert 5 not in r.ma and 60 not in r.ma
    assert r.bars == 3


# ---------- 腾讯 K 线解析 ----------

def test_parse_tencent_kline():
    payload = {
        "code": 0,
        "data": {
            "sh600519": {
                "qfqday": [
                    ["2026-08-17", "1290.0", "1293.09", "1300.0", "1285.0", "25000"],
                    ["2026-08-18", "1291.0", "1287.32", "1295.0", "1280.0", "31000"],
                ]
            }
        },
    }
    df = _parse_tencent_kline(payload, "sh600519", "600519")
    assert len(df) == 2
    assert list(df["收盘"]) == [1293.09, 1287.32]
    # 第二根涨跌幅 = 1287.32/1293.09 - 1
    assert df["涨跌幅"].iloc[1] == pytest.approx((1287.32 / 1293.09 - 1) * 100)
    assert df["涨跌幅"].iloc[0] == 0.0
    # 可直接进入指标计算
    r = compute_metrics(df, code="600519")
    assert r.bars == 2
    assert r.latest_close == 1287.32


def test_parse_tencent_kline_empty_raises():
    import pytest as _pytest

    with _pytest.raises(RuntimeError):
        _parse_tencent_kline({"data": {}}, "sh600519", "600519")


# ---------- 波动画像与缓存 ----------

def test_brief_profile():
    df = make_df([100.0 + i for i in range(70)])
    r = compute_metrics(df, code="600519", name="测试股")
    text = brief_profile(r)
    assert "近70日" in text
    assert "年化波动" in text
    assert "最大回撤" in text
    assert "MA20上方" in text  # 稳定上行，收盘在 MA20 上方
    assert "量比" in text


def test_profile_cache_per_day(monkeypatch):
    import ashare_monitor.analysis as analysis_mod

    calls = []

    def fake_analyze(code, days=250, market="ashare"):
        calls.append((code, market))
        df = make_df([100.0, 101.0, 102.0])
        return compute_metrics(df, code=code)

    monkeypatch.setattr(analysis_mod, "analyze", fake_analyze)
    cache = ProfileCache(days=60)
    p1 = cache.get("600519")
    p2 = cache.get("600519")   # 同一天应命中缓存，不再拉取
    p3 = cache.get("000001")   # 不同股票独立拉取
    p4 = cache.get("600519", market="hk")  # 同代码不同市场独立缓存
    assert p1 == p2
    assert p3 is not None
    assert p4 is not None
    assert calls == [("600519", "ashare"), ("000001", "ashare"), ("600519", "hk")]


def test_profile_cache_failure_returns_none(monkeypatch):
    import ashare_monitor.analysis as analysis_mod

    def boom(code, days=250, market="ashare"):
        raise ConnectionError("network down")

    monkeypatch.setattr(analysis_mod, "analyze", boom)
    cache = ProfileCache()
    assert cache.get("600519") is None  # 失败返回 None，不抛异常
