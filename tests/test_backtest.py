"""持有期回测单元测试（合成 K 线）。"""

import datetime

import pytest

from ashare_monitor.backtest import backtest, dca_backtest


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


# ---------- 定投回测 ----------

def make_monthly_rows() -> list[dict]:
    """24 个月日 K：每月 20 个交易日，价格每 6 个月上涨 20%。"""
    rows = []
    price = 10.0
    for m in range(24):
        for d in range(20):
            rows.append({
                "date": f"{2024 + m // 12}-{m % 12 + 1:02d}-{d + 1:02d}",
                "open": price * 0.99, "close": price,
                "high": price * 1.02, "low": price * 0.98, "volume": 10000.0,
            })
        price *= 1.2
    return rows


def test_dca_stats():
    rows = make_monthly_rows()
    result = dca_backtest("600001", "ashare", amount=10000, months=12,
                          hold_days=250, rows=rows)
    assert result["trades"] == 12
    # 每月买入持有 250 日：价格 6 个月涨 20%，250 交易日约 12 个月 → 平均收益显著为正
    assert result["avg_return_pct"] > 10
    assert result["win_rate_pct"] == 100.0
    assert result["best_pct"] >= result["median_return_pct"] >= result["worst_pct"]
    assert len(result["detail"]) == 12
    # 每笔买卖日差 ≈ 250 个交易日
    assert result["detail"][0]["return_pct"] > 0


def test_dca_insufficient_data():
    rows = make_monthly_rows()[:100]   # 不到 5 个月
    import pytest as _pytest

    with _pytest.raises(RuntimeError):
        dca_backtest("600001", "ashare", months=60, hold_days=250, rows=rows)


# ---------- 多标的对比与可视化 ----------

def test_dca_compare():
    from ashare_monitor.backtest import dca_compare

    # 温和涨幅（每月 +5%），保证港股整手 500 股全程买得起
    def make_slow_rows():
        rows = []
        price = 10.0
        for m in range(30):
            for d in range(20):
                rows.append({
                    "date": f"{2024 + m // 12}-{m % 12 + 1:02d}-{d + 1:02d}",
                    "open": price * 0.99, "close": price,
                    "high": price * 1.02, "low": price * 0.98, "volume": 10000.0,
                })
            price *= 1.05
        return rows

    results = dca_compare(
        ["600001", "01211"],
        amount=10000, months=12, hold_days=250,
        rows_map={"600001": make_slow_rows(), "01211": make_slow_rows()},
    )
    assert len(results) == 2
    a, h = results[0], results[1]
    assert a["code"] == "600001" and a["market"] == "ashare"
    assert h["code"] == "01211" and h["market"] == "hk"     # 5 位推断港股
    assert a["trades"] == 12 and h["trades"] == 12
    assert a["avg_return_pct"] > 0 and "error" not in a
    assert "error" not in h


def test_dca_compare_error_tolerated():
    from ashare_monitor.backtest import dca_compare

    results = dca_compare(["000001", "999999"], amount=10000, months=12,
                          hold_days=250, rows_map={"000001": make_monthly_rows()})
    assert any("error" in r for r in results)   # 无数据的标的不抛异常


def test_backtest_chart_data():
    from ashare_monitor.backtest import backtest_chart_data

    rows = make_rows([10.0] * 5 + [12.0] * 25)
    data = backtest_chart_data("600001", "ashare", buy_date="2024-01-03",
                               hold_days=10, amount=10000, rows=rows)
    assert data["buy"]["x"] == "2024-01-03"
    assert data["buy"]["y"] == 10.0
    assert data["sell"]["y"] == 12.0
    assert data["return_pct"] == pytest.approx(20.0)
    assert data["buy"]["x"] in data["dates"] and data["sell"]["x"] in data["dates"]
    assert len(data["kdata"]) == len(data["dates"]) == len(data["volumes"])


def test_build_backtest_html():
    from ashare_monitor.backtest import build_backtest_html

    data = {
        "title": "600001 回测", "return_pct": 20.0,
        "dates": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "kdata": [[10, 10.2, 9.9, 10.3], [10.2, 10.5, 10.1, 10.6], [10.5, 12, 10.4, 12.1]],
        "volumes": [1000, 1200, 1100],
        "buy": {"x": "2024-01-01", "y": 10.0},
        "sell": {"x": "2024-01-03", "y": 12.0},
    }
    html = build_backtest_html(data)
    assert "renderBt" in html
    assert "candlestick" in html
    assert "+20.00%" in html
    assert "B 买" in html and "S 卖" in html
    assert "不构成投资建议" in html
