"""全市场异动扫描单元测试（合成快照，不依赖网络）。"""

from datetime import datetime

import pandas as pd
import pytest

from ashare_monitor.quotes import Quote
from ashare_monitor.screener import ScanConfig, scan_market, _snapshot_from_quotes


def make_snapshot() -> pd.DataFrame:
    rows = [
        # 代码 名称 最新价 涨跌幅 换手率 量比 振幅 成交额
        ["600001", "涨停股", 10.0, 10.01, 8.0, 3.5, 12.0, 5e8],
        ["600002", "大跌股", 5.0, -9.98, 6.0, 1.2, 10.0, 3e8],
        ["600003", "放量股", 8.0, 3.0, 4.0, 4.2, 5.0, 9e8],
        ["600004", "高换手", 12.0, 2.0, 15.0, 2.1, 6.0, 2e8],
        ["600005", "ST垃圾", 1.5, 5.0, 20.0, 5.0, 8.0, 1e8],
        ["600006", "仙股", 0.8, 10.0, 3.0, 2.0, 7.0, 5e7],
        ["600007", "停牌", 20.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ["600008", "普通股", 15.0, 0.5, 1.0, 0.8, 2.0, 1e8],
        ["600009", "跌停股", 3.0, -10.0, 9.0, 3.0, 10.5, 4e8],
        ["600010", "中等放量", 9.0, 1.5, 2.0, 2.5, 3.5, 2e8],
    ]
    df = pd.DataFrame(
        rows,
        columns=["代码", "名称", "最新价", "涨跌幅", "换手率", "量比", "振幅", "成交额"],
    )
    return df


def test_scan_boards_filtering():
    result = scan_market(make_snapshot(), cfg=ScanConfig(limit=5))
    # 涨幅榜第一是涨停股（ST 与仙股被剔除）
    assert result.gainers[0]["code"] == "600001"
    assert all(r["code"] != "600005" for r in result.gainers)     # 剔除 ST
    assert all(r["code"] != "600006" for r in result.gainers)     # 剔除低价
    # 跌幅榜：跌停股与大跌股
    assert result.losers[0]["code"] == "600009"
    # 放量异动：量比 >= 2 且降序
    assert result.volume_spikes[0]["code"] == "600003"
    assert all(r["volume_ratio"] >= 2.0 for r in result.volume_spikes)
    assert "600007" not in [r["code"] for r in result.gainers]    # 停牌剔除
    assert "600007" not in [r["code"] for r in result.volume_spikes]


def test_scan_hot_turnover():
    result = scan_market(make_snapshot(), cfg=ScanConfig(limit=3))
    assert result.hot_turnover[0]["code"] == "600004"   # 换手 15% 最高
    assert all(r["turnover_rate"] >= 5.0 for r in result.hot_turnover)


def test_scan_wide_amplitude():
    result = scan_market(make_snapshot(), cfg=ScanConfig(limit=5))
    assert result.wide_amplitude[0]["code"] == "600001"  # 振幅 12% 最高


def test_scan_exclude_st_disabled():
    result = scan_market(make_snapshot(), cfg=ScanConfig(exclude_st=False, min_price=0))
    codes = [r["code"] for r in result.gainers]
    assert "600005" in codes


def test_scan_row_safe_missing_values():
    df = make_snapshot().copy()
    df.loc[0, "量比"] = None
    result = scan_market(df, cfg=ScanConfig(limit=5))
    # 缺失量比不影响榜单生成，放量榜不包含该股
    assert result.gainers[0]["code"] == "600001"
    assert result.volume_spikes[0]["code"] == "600003"


# ---------- 新浪降级路径 ----------

def make_quote(code="600001", name="测试股", price=10.0, change_pct=5.0,
               high=11.0, low=9.5, prev_close=9.5) -> Quote:
    return Quote(
        code=code, name=name, price=price, change_pct=change_pct,
        change=price - prev_close, volume=1000, turnover=1e7,
        high=high, low=low, open=9.8, prev_close=prev_close,
        timestamp=datetime(2026, 8, 18, 15, 0),
    )


def test_snapshot_from_quotes():
    quotes = [
        make_quote("600001", "甲", 10.0, 5.0),
        make_quote("600002", "乙", 20.0, -3.0, high=21.0, low=19.0, prev_close=20.6),
    ]
    df = _snapshot_from_quotes(quotes)
    assert list(df["代码"]) == ["600001", "600002"]
    # 新浪无换手率/量比 → None
    assert df["换手率"].isna().all() and df["量比"].isna().all()
    # 振幅列已计算
    assert df.loc[0, "振幅"] == pytest.approx((11.0 - 9.5) / 9.5 * 100)


def test_scan_with_sina_snapshot():
    """新浪快照（无量比/换手）也能正常出涨幅/跌幅/振幅榜。"""
    quotes = [
        make_quote("600001", "甲", 10.0, 9.9, high=10.8, low=9.2, prev_close=9.1),
        make_quote("600002", "乙", 20.0, -9.5, high=20.5, low=18.5, prev_close=22.1),
        make_quote("600003", "丙", 5.0, 1.0, high=5.2, low=4.8, prev_close=4.95),
    ]
    result = scan_market(_snapshot_from_quotes(quotes), cfg=ScanConfig(limit=5))
    assert result.gainers[0]["code"] == "600001"
    assert result.losers[0]["code"] == "600002"
    assert result.wide_amplitude[0]["code"] == "600001"
    # 无量比/换手数据 → 放量榜与换手榜为空
    assert result.volume_spikes == []
    assert result.hot_turnover == []
