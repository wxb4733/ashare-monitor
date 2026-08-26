"""历史回填与上市以来分析单元测试。"""

import pytest

from ashare_monitor.backfill import KNOWN_IPO_DATES, analyze_history


def make_klines() -> list[dict]:
    """模拟比亚迪 A 股 5 年日 K（先横盘再上涨，最近回落）。"""
    rows = []
    import datetime

    d = datetime.date(2011, 6, 30)
    price = 20.0
    for i in range(1250):  # 5 年 × 250 天
        if i < 500:
            pass                 # 前两年横盘
        elif i < 1000:
            price *= 1.01        # 中间两年上涨 → 历史最高在 ~999
        else:
            price *= 0.995       # 最近一年回落
        rows.append({
            "date": str(d),
            "open": price * 0.99, "close": price,
            "high": price * 1.02, "low": price * 0.98,
            "volume": 100000.0,
        })
        d += datetime.timedelta(days=1)
    return rows


def test_analyze_history_stats():
    h = analyze_history(make_klines())
    assert h["bars"] == 1250
    assert h["years"] == pytest.approx(5.0, rel=0.1)
    assert h["first_date"] == "2011-06-30"
    # 历史最高在上涨段末尾（约 i=999）
    assert h["all_time_high_date"] > "2012-01-01"
    assert h["all_time_high"] > h["all_time_low"]
    # 当前价低于历史最高 → 回撤为负
    assert h["drawdown_pct"] < 0
    # 区间位置在 0-100
    assert 0 <= h["position_pct"] <= 100
    # 年化收益与总涨幅同号
    assert (h["annualized_pct"] > 0) == (h["total_return_pct"] > 0)


def test_analyze_history_insufficient():
    with pytest.raises(RuntimeError):
        analyze_history([{"date": "2026-01-01", "close": 10.0}])


def test_known_ipo_dates():
    assert KNOWN_IPO_DATES[("ashare", "002594")] == "2011-06-30"
    assert KNOWN_IPO_DATES[("hk", "01211")] == "2002-07-31"


def test_klines_storage_roundtrip(tmp_path):
    from ashare_monitor.storage import count_klines, load_klines, record_klines

    db = str(tmp_path / "test.db")
    rows = [
        ("2026-08-18", 10.0, 10.5, 10.6, 9.9, 1000.0),
        ("2026-08-19", 10.5, 10.8, 10.9, 10.4, 1200.0),
    ]
    new = record_klines(rows, "ashare", "002594", db_path=db)
    assert new == 2
    # 重复入库去重
    assert record_klines(rows, "ashare", "002594", db_path=db) == 0
    loaded = load_klines("002594", "ashare", db_path=db)
    assert len(loaded) == 2
    assert loaded[0]["close"] == 10.5
    assert loaded[1]["date"] == "2026-08-19"
    assert count_klines("002594", "ashare", db_path=db) == 2
    # 不同市场隔离
    assert count_klines("01211", "hk", db_path=db) == 0


def test_financials_storage_roundtrip(tmp_path):
    from ashare_monitor.fundamentals import FinancialPeriod
    from ashare_monitor.storage import load_financials, record_financials

    db = str(tmp_path / "test.db")
    items = [
        FinancialPeriod("2026-06-30", 922.8, 445.2, 1.3, -1.9, 16.8, 89.6, 48.2, 35.57, 56.55),
        FinancialPeriod("2026-03-31", 548.0, 272.9, 6.3, 1.5, 10.6, 89.8, 49.8, 21.76, 21.9),
    ]
    new, exist = record_financials(items, "600519", name="贵州茅台", db_path=db)
    assert (new, exist) == (2, 0)
    new, exist = record_financials(items, "600519", db_path=db)
    assert (new, exist) == (0, 2)
    loaded = load_financials("600519", db_path=db)
    assert len(loaded) == 2
    assert loaded[0]["report_date"] == "2026-06-30"
    assert loaded[0]["revenue"] == 922.8 and loaded[0]["roe"] == 16.8


def test_sina_kline_parse(monkeypatch):
    """新浪 jsonp 解析：剥离反爬前缀、生成标准行格式。"""
    import json as _json

    from ashare_monitor import backfill

    payload = [{"day": "2026-08-25", "open": "10.68", "high": "10.76",
                "low": "10.60", "close": "10.66", "volume": "126895206"},
               {"day": "2026-08-24", "open": "10.50", "high": "10.60",
                "low": "10.40", "close": "10.55", "volume": "100000000"}]
    body = ("/*<script>location.href='//sina.com';</script>*/\n"
            "var _x=(" + _json.dumps(payload) + ")")

    class _Resp:
        text = body

        def raise_for_status(self):
            pass

    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    rows = backfill._backfill_kline_sina("601939", "ashare", "2020-01-01")
    assert len(rows) == 2
    assert rows[0] == ("2026-08-25", 10.68, 10.66, 10.76, 10.60, 126895206)
    assert rows[1][0] == "2026-08-24"


def test_backfill_kline_sina_fallback(monkeypatch):
    """backfill_kline 降级链：akshare → 腾讯 → 新浪（全失败时新浪兜底落库）。"""
    from ashare_monitor import backfill

    calls = []

    def _ak_boom(*a, **k):
        calls.append("akshare")
        raise RuntimeError("akshare 不可达")

    def _tx_boom(*a, **k):
        calls.append("tencent")
        raise RuntimeError("腾讯限流")

    def _sina_ok(*a, **k):
        calls.append("sina")
        return [("2026-08-25", 1.0, 1.1, 1.2, 0.9, 100)]

    monkeypatch.setattr(backfill, "record_klines",
                        lambda rows, market, code: len(rows))
    # akshare 函数体在 backfill_kline 内以 import 方式调用，须 patch 该函数本身
    import akshare as ak  # noqa: F401

    def _fake_zh_a_hist(*a, **k):
        raise RuntimeError("东财不可达")

    monkeypatch.setattr(ak, "stock_zh_a_hist", _fake_zh_a_hist)
    monkeypatch.setattr(backfill, "_backfill_kline_tencent", _tx_boom)
    monkeypatch.setattr(backfill, "_backfill_kline_sina", _sina_ok)
    new, _ = backfill.backfill_kline("601939", "ashare")
    assert new == 1
    assert calls == ["tencent", "sina"]
