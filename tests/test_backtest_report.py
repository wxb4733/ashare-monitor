"""回测报告升级（统计扩展/网格优化/HTML 报告）单元测试。"""

import pytest


def _mk_result():
    """构造最小 backtest_rebalanced 返回结构。"""
    dates = [f"2024-{1 + i // 28:02d}-{i % 28 + 1:02d}" for i in range(120)]
    n = len(dates)
    navs = [i * 0.3 for i in range(n)]          # 单调上行
    return {
        "dates": dates,
        "periodic": {"total": 35.0, "annual": 28.0, "max_dd": 12.0,
                     "sharpe": 1.1, "sortino": 1.5, "win_rate": 60.0,
                     "profit_factor": 1.8, "best_day": 5.0,
                     "worst_day": -3.0, "days": n},
        "buy_hold_cost": {"total": 40.0, "annual": 30.0, "max_dd": 11.0,
                          "sharpe": 1.2, "sortino": 1.6, "win_rate": 62.0,
                          "profit_factor": 1.9, "best_day": 4.0,
                          "worst_day": -2.0, "days": n},
        "benchmark": {"total": 20.0, "annual": 15.0, "max_dd": 10.0,
                      "sharpe": 0.8, "sortino": 1.0, "win_rate": 55.0,
                      "profit_factor": 1.4, "best_day": 3.0,
                      "worst_day": -2.5, "days": n},
        "frequency": "monthly", "cost_bps": 5.0, "limit_pct": 9.5,
        "nav_series": {"dates": dates, "buy_hold": navs,
                       "periodic": navs, "benchmark": navs},
    }


def test_ret_stats_extended():
    """_ret_stats 新增 5 项统计（pyfolio 模式）。"""
    from ashare_monitor.strategy import _ret_stats

    nav_pcts = [0.0, 1.0, 0.5, 2.0, -1.0, 1.5, 3.0, -0.5]
    dates = [f"2024-01-{i + 1:02d}" for i in range(len(nav_pcts))]
    s = _ret_stats(nav_pcts, dates)
    # 旧字段保留
    assert "total" in s and "annual" in s and "sharpe" in s
    # 新字段
    assert "sortino" in s and "win_rate" in s and "profit_factor" in s
    assert "best_day" in s and "worst_day" in s
    assert 0 < s["win_rate"] < 100
    assert s["best_day"] > 0 and s["worst_day"] < 0
    assert s["profit_factor"] > 0.0


def test_backtest_nav_series_aligned(monkeypatch):
    """nav_series 与 dates 等长对齐（HTML 绘图前提）。"""
    from ashare_monitor import strategy
    import pandas as pd

    def fake_load(code, market):
        rows = []
        for i in range(120):
            m = 1 + i // 30
            d = i % 30 + 1
            rows.append({"date": f"2024-{m:02d}-{d:02d}", "open": 10.0,
                         "close": 10.0 + i * 0.2, "high": 11.0,
                         "low": 9.0, "volume": 1000.0})
        return rows

    monkeypatch.setattr("ashare_monitor.storage.load_klines", fake_load)
    idx_df = pd.DataFrame({
        "date": [f"2024-{1 + i // 30:02d}-{i % 30 + 1:02d}" for i in range(120)],
        "open": [100.0] * 120, "high": [101.0] * 120, "low": [99.0] * 120,
        "close": [100.0 + i * 0.1 for i in range(120)],
        "volume": [1.0] * 120,
    })
    monkeypatch.setattr("akshare.stock_zh_index_daily",
                        lambda symbol="sh000300": idx_df)
    r = strategy.portfolio_backtest_rebalanced(
        ["600519", "000001"], frequency="monthly", cost_bps=5.0)
    nav = r["nav_series"]
    n = len(r["dates"])
    assert len(nav["dates"]) == n
    assert len(nav["periodic"]) == n
    assert len(nav["buy_hold"]) == n
    assert len(nav["benchmark"]) == n
    # 新统计字段
    assert "sortino" in r["periodic"] and "win_rate" in r["periodic"]


def test_optimize_backtest(monkeypatch):
    """网格优化：数量 = 频率×成本，最优按夏普。"""
    from ashare_monitor import strategy

    calls = []

    def fake_backtest(codes, start=None, frequency="monthly", cost_bps=5.0,
                      limit_pct=9.5):
        calls.append((frequency, cost_bps))
        return {"periodic": {"annual": 20.0 + cost_bps * 0.1,
                             "total": 30.0, "max_dd": 12.0,
                             "sharpe": 1.0 - cost_bps * 0.01,
                             "sortino": 1.2, "win_rate": 58.0}}
    monkeypatch.setattr("ashare_monitor.strategy.portfolio_backtest_rebalanced",
                        fake_backtest)
    grid = strategy.optimize_backtest(
        ["600519"], frequencies=("monthly", "quarterly"),
        costs=(0.0, 5.0))
    assert len(grid["results"]) == 4
    assert grid["best"]["cost_bps"] == 0.0       # 夏普最高
    assert len(calls) == 4
    assert ("monthly", 0.0) in calls and ("quarterly", 5.0) in calls


def test_render_html(tmp_path):
    """HTML 报告：统计表 + 净值曲线 SVG + 月度热力图。"""
    from ashare_monitor.backtest_report import render_backtest_html

    path = render_backtest_html(_mk_result(), ["600519", "002594"],
                                str(tmp_path / "bt.html"))
    content = open(path, encoding="utf-8").read()
    assert "<svg" in content and "polyline" in content     # 净值曲线
    assert "月度收益热力图" in content                       # 热力图
    assert "Sortino" in content and "盈亏比" in content     # 9 项统计
    assert "红涨绿跌" in content
    assert "600519" in content


def test_monthly_returns():
    """月度收益切分正确。"""
    from ashare_monitor.backtest_report import _monthly_returns

    dates = ["2024-01-01", "2024-01-31", "2024-02-01", "2024-02-28",
             "2024-03-01"]
    nav_pcts = [0.0, 10.0, 10.0, 20.0, 20.0]      # 2 月收益 = 1.2/1.1-1
    mr = _monthly_returns(dates, nav_pcts)
    assert "2024" in mr
    assert mr["2024"][1] == pytest.approx(10.0)                # 1 月 +10%
    assert mr["2024"][2] == pytest.approx((1.2 / 1.1 - 1) * 100,
                                          abs=0.01)            # 2 月 +9.09%
