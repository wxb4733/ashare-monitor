"""低频策略引擎 + 模拟交易单元测试。"""

import pytest


def test_dividend_strategy(monkeypatch):
    from ashare_monitor.strategy import dividend_strategy

    monkeypatch.setattr(
        "ashare_monitor.screen.screen_dividend",
        lambda top_n, min_yield: [
            type("H", (), {"code": "600900", "name": "长江电力"})(),
            type("H", (), {"code": "601088", "name": "中国神华"})(),
            type("H", (), {"code": "600519", "name": "贵州茅台"})(),
            type("H", (), {"code": "000651", "name": "格力电器"})(),
        ])
    targets = dividend_strategy(top_n=4, capital=100_000.0, min_yield=3.0)
    assert len(targets) == 4
    assert targets[0].weight == pytest.approx(25.0)     # 等权
    assert targets[0].target_value == pytest.approx(25_000.0)
    assert targets[0].code == "600900"


def test_execute_paper_trade(tmp_path, monkeypatch):
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "paper.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))

    class _Q:
        code = "600900"
        price = 28.5

    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare": ([_Q()], "tencent"))
    targets = [strategy.TargetPosition("600900", "长江电力", 100.0, 100_000.0)]
    result = strategy.execute_paper_trade(targets, dry_run=True)
    assert result["fills"][0]["shares"] == 3500      # 100000//28.5//100*100
    assert result["total_cost"] == pytest.approx(99_750.0, abs=0.01)
    # 落库
    result2 = strategy.execute_paper_trade(targets)
    pos = strategy.load_paper_positions()
    assert len(pos) == 1
    assert pos[0]["shares"] == 3500
    assert pos[0]["avg_cost"] == pytest.approx(28.5)


def test_execute_paper_trade_reject(tmp_path, monkeypatch):
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "paper2.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))

    class _Q:
        code = "600519"
        price = 1450.0

    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare": ([_Q()], "tencent"))
    # 10000 元买不起 1 手茅台（1450×100=145000）
    targets = [strategy.TargetPosition("600519", "贵州茅台", 100.0, 10_000.0)]
    result = strategy.execute_paper_trade(targets, dry_run=True)
    assert not result["fills"]
    assert result["rejected"][0]["reason"].startswith("资金不足一手")


def test_portfolio_backtest(tmp_path, monkeypatch):
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    # mock 本地 K 线：两只标的（一涨一跌）+ 沪深 300 指数
    def fake_load(code, market):
        dates = [f"2024-0{i}-0{j}" for i in range(1, 3) for j in range(1, 3)]
        rows = [{"date": d, "close": 10.0 + i * 0.5} for i, d in enumerate(dates)]
        return rows

    monkeypatch.setattr("ashare_monitor.strategy.load_klines", fake_load)

    import pandas as pd

    idx_df = pd.DataFrame({
        "date": [f"2024-0{i}-0{j}" for i in range(1, 3) for j in range(1, 3)],
        "open": [100.0] * 4, "high": [101.0] * 4, "low": [99.0] * 4,
        "close": [100.0 + i for i in range(4)],
        "volume": [1.0] * 4,
    })

    def fake_index(symbol):
        return idx_df

    monkeypatch.setattr("akshare.stock_zh_index_daily", fake_index)
    result = strategy.portfolio_backtest(
        ["600519", "000001"], names={"600519": "茅台", "000001": "平安"})
    assert result["portfolio"]["days"] == 3
    assert result["portfolio"]["total"] > 0
    assert result["benchmark"]["total"] > 0
    assert "excess_annual" in result
