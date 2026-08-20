"""持有期回测单元测试（合成 K 线）。"""

import datetime

import pytest

from ashare_monitor.backtest import backtest


def make_rows(prices: list[float], start: str = "2024-01-02") -> list[dict]:
    d = datetime.date.fromisoformat(start)
    rows = []
    for p in prices:
        rows.append({
            "date": str(d),
            "open": p * 0.99, "close": p,
            "high": p * 1.02, "low": p * 0.98,
            "volume": 100000.0,
        })
        d += datetime.timedelta(days=1)
    return rows


def test_backtest_basic_profit():
    """10 元买入涨到 12 元，持有 10 天，收益率 +20%。"""
    prices = [10.0] * 5 + [12.0] * 15
    rows = make_rows(prices)
    results = backtest("600001", "ashare", buy_date="2024-01-03",
                       amount=10000, hold_days=[10], rows=rows)
    r = results[0]
    assert r["status"] == "ok"
    assert r["buy_date"] == "2024-01-03"
    assert r["buy_price"] == 10.0
    assert r["sell_price"] == 12.0
    assert r["shares"] == 1000          # 10000/10=1000 股（整手不变）
    assert r["buy_amount"] == 10000.0
    assert r["sell_amount"] == 12000.0
    assert r["return_pct"] == pytest.approx(20.0)
    assert r["hold_days"] == 10


def test_backtest_loss_and_high_low():
    prices = [10.0, 10.0, 8.0, 8.0, 8.0, 8.0]
    rows = make_rows(prices)
    results = backtest("600001", "ashare", buy_date="2024-01-02",
                       amount=10000, hold_days=[4], rows=rows)
    r = results[0]
    assert r["return_pct"] == pytest.approx(-20.0)   # 10 → 8
    assert r["high"] == pytest.approx(10.2)          # 含买入日
    assert r["low"] == pytest.approx(7.84)           # 8 * 0.98
    assert r["annualized_pct"] < 0


def test_backtest_buy_date_after_market_start():
    """买入日早于数据首日 → 用首日；买入日晚于末日前 → 用最后可交易日。"""
    rows = make_rows([10.0] * 30, start="2024-02-01")
    # 早于首日
    r1 = backtest("600001", "ashare", buy_date="2020-01-01",
                  amount=1000, hold_days=[5], rows=rows)[0]
    assert r1["buy_date"] == "2024-02-01"
    # 晚于数据末（用 rows[-2]）
    r2 = backtest("600001", "ashare", buy_date="2030-01-01",
                  amount=1000, hold_days=[5], rows=rows)[0]
    assert r2["buy_date"] == rows[-2]["date"]


def test_backtest_insufficient_data():
    rows = make_rows([10.0] * 20)
    results = backtest("600001", "ashare", buy_date="2024-01-02",
                       amount=1000, hold_days=[500], rows=rows)
    assert results[0]["status"] == "数据不足"
    assert "available" in results[0]


def test_backtest_amount_too_small():
    rows = make_rows([10.0] * 20)
    results = backtest("600001", "ashare", buy_date="2024-01-02",
                       amount=50, hold_days=[5], rows=rows)   # 50 元不足 1 手
    assert results[0]["status"] == "金额不足一手"


def test_backtest_hk_lot_500():
    """港股整手 500 股。"""
    rows = make_rows([100.0] * 10 + [110.0] * 10)
    results = backtest("01211", "hk", buy_date="2024-01-02",
                       amount=200000, hold_days=[10], rows=rows)
    r = results[0]
    assert r["shares"] == 2000          # 200000/100=2000 股（500 的整倍数）
    assert r["return_pct"] == pytest.approx(10.0)


def test_backtest_multiple_holds():
    rows = make_rows([10.0] * 10 + [12.0] * 10 + [9.0] * 10)
    results = backtest("600001", "ashare", buy_date="2024-01-02",
                       amount=10000, hold_days=[10, 20], rows=rows)
    assert len(results) == 2
    assert results[0]["return_pct"] == pytest.approx(20.0)    # 10→12
    assert results[1]["return_pct"] == pytest.approx(-10.0)   # 10→9
