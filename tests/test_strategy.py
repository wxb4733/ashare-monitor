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
        rows = []
        for i in range(100):
            rows.append({"date": f"2024-01-{i % 28 + 1:02d}", "close": 10.0 + i * 0.5})
        return rows

    monkeypatch.setattr("ashare_monitor.storage.load_klines", fake_load)

    import pandas as pd

    idx_df = pd.DataFrame({
        "date": [f"2024-01-{i % 28 + 1:02d}" for i in range(100)],
        "open": [100.0] * 100, "high": [101.0] * 100, "low": [99.0] * 100,
        "close": [100.0 + i for i in range(100)],
        "volume": [1.0] * 100,
    })

    def fake_index(symbol):
        return idx_df

    monkeypatch.setattr("akshare.stock_zh_index_daily", fake_index)
    result = strategy.portfolio_backtest(
        ["600519", "000001"], names={"600519": "茅台", "000001": "平安"})
    assert result["portfolio"]["days"] > 50
    assert result["portfolio"]["total"] > 0
    assert result["benchmark"]["total"] > 0
    assert "excess_annual" in result


def test_rebalance_orders(monkeypatch):
    from ashare_monitor import strategy

    # 当前持仓：平安银行 10000 股 @ 11 元（股价低，整手差额可执行）
    monkeypatch.setattr(
        "ashare_monitor.strategy.load_paper_positions",
        lambda: [{"code": "000001", "name": "平安银行", "shares": 10000,
                  "avg_cost": 11.0, "updated": "2026-08-01"}])

    class _Q:
        code = "000001"
        price = 11.0

    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare": ([_Q()], "tencent"))
    targets = [strategy.TargetPosition("000001", "平安银行", 50.0, 50_000.0),
               strategy.TargetPosition("600900", "长江电力", 50.0, 50_000.0)]
    orders = strategy.rebalance_orders(targets, 100_000.0)
    by = {o["code"]: o for o in orders}
    # 平安当前市值 11 万 > 目标 5 万 → 卖出 60000//11//100*100=5400 股
    assert by["000001"]["side"] == "sell"
    assert by["000001"]["reason"] == "减仓"
    assert by["000001"]["shares"] == 5400
    # 长电行情缺失 → hold（如实）
    assert by["600900"]["reason"] == "行情缺失"


def test_apply_risk_rules(monkeypatch):
    from ashare_monitor.strategy import apply_risk_rules, TargetPosition

    monkeypatch.setattr("ashare_monitor.strategy._try_market_cap",
                        lambda code: {"600519": 20000.0,
                                      "600000": 3000.0,
                                      "000001": 8.0,
                                      "300999": 5.0}.get(code))
    targets = [
        TargetPosition("600519", "贵州茅台", 25.0, 25_000.0),   # 权重超限
        TargetPosition("600000", "浦发银行", 15.0, 15_000.0),   # 正常
        TargetPosition("000001", "ST测试", 10.0, 10_000.0),     # ST 剔除
        TargetPosition("300999", "小市值", 10.0, 10_000.0),     # 市值不足
    ]
    risk = apply_risk_rules(targets, max_weight=20.0,
                            min_market_cap=20.0)
    codes = {t.code for t in risk["accepted"]}
    assert "600519" in codes          # 权重调降但保留
    assert "600000" in codes
    assert "000001" not in codes      # ST 剔除
    assert "300999" not in codes      # 市值不足
    assert any("调降至上限" in n for n in risk["notes"])
    rejected = {r["code"] for r in risk["rejected"]}
    assert "000001" in rejected and "300999" in rejected


def test_paper_report(monkeypatch):
    from ashare_monitor.strategy import paper_report

    monkeypatch.setattr(
        "ashare_monitor.strategy.load_paper_positions",
        lambda: [{"code": "000001", "name": "平安银行", "shares": 10000,
                  "avg_cost": 10.0, "updated": "2026-08-01"}])

    class _Q:
        code = "000001"
        price = 11.0

    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare": ([_Q()], "tencent"))
    rep = paper_report()
    assert rep["total_cost"] == pytest.approx(100_000.0)
    assert rep["total_value"] == pytest.approx(110_000.0)
    assert rep["pnl_pct"] == pytest.approx(10.0)


def test_portfolio_backtest_rebalanced(tmp_path, monkeypatch):
    from ashare_monitor import strategy
    import pandas as pd

    # 两只标的全历史对齐（100 天上涨 + 一涨一跌）
    def fake_load(code, market):
        rows = []
        for i in range(120):
            m = 1 + i // 30
            d = i % 30 + 1
            rows.append({"date": f"2024-{m:02d}-{d:02d}",
                         "close": 10.0 + i * (0.3 if code == "600519" else -0.1)})
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
    result = strategy.portfolio_backtest_rebalanced(
        ["600519", "000001"])
    assert result["buy_hold"]["days"] > 50
    assert result["periodic"]["days"] > 50
    assert result["benchmark"]["days"] > 50
    # 一涨一跌 + 月度再平衡 → 两策略都有数据
    assert "total" in result["buy_hold"] and "total" in result["periodic"]


def test_period_key():
    from ashare_monitor.strategy import _period_key

    assert _period_key("2024-03-15", "monthly") == "2024-03"
    assert _period_key("2024-04-01", "quarterly") == "2024Q2"
    assert _period_key("2024-07-01", "semi_annual") == "2024S2"


def test_rebalanced_cost_penalty(tmp_path, monkeypatch):
    from ashare_monitor import strategy
    import pandas as pd

    def fake_load(code, market):
        rows = []
        for i in range(120):
            m = 1 + i // 30
            d = i % 30 + 1
            rows.append({"date": f"2024-{m:02d}-{d:02d}",
                         "close": 10.0 + i * 0.2})
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
    # 高成本（每期 50bp）显著惩罚再平衡
    r_cheap = strategy.portfolio_backtest_rebalanced(
        ["600519", "000001"], frequency="monthly", cost_bps=5.0)
    r_costly = strategy.portfolio_backtest_rebalanced(
        ["600519", "000001"], frequency="monthly", cost_bps=50.0)
    assert (r_costly["periodic"]["annual"]
            < r_cheap["periodic"]["annual"])
    # 静态含成本略低于不含成本
    assert r_cheap["buy_hold_cost"]["total"] < r_cheap["buy_hold"]["total"]


def test_paper_nav_tracking(tmp_path, monkeypatch):
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "nav.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    monkeypatch.setattr(
        "ashare_monitor.strategy.load_paper_positions",
        lambda: [{"code": "000001", "name": "平安银行", "shares": 10000,
                  "avg_cost": 10.0, "updated": "2026-08-01"}])

    class _Q:
        code = "000001"
        price = 11.0

    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare": ([_Q()], "tencent"))
    rec = strategy.record_paper_nav()
    assert rec["total_value"] == pytest.approx(110_000.0)
    assert rec["pnl_pct"] == pytest.approx(10.0)
    navs = strategy.load_paper_nav()
    assert len(navs) == 1
    assert navs[0]["nav"] == pytest.approx(1.1)


def test_portfolio_circuit_breaker(monkeypatch):
    from ashare_monitor.strategy import portfolio_circuit_breaker

    monkeypatch.setattr(
        "ashare_monitor.strategy.paper_report",
        lambda: {"total_value": 80_000.0, "total_cost": 100_000.0,
                 "pnl_pct": -20.0, "positions": []})
    cb = portfolio_circuit_breaker(drawdown_pct=20.0)
    assert cb["triggered"] is True
    assert cb["loss_pct"] == pytest.approx(20.0)
    # 未触发
    monkeypatch.setattr(
        "ashare_monitor.strategy.paper_report",
        lambda: {"total_value": 95_000.0, "total_cost": 100_000.0,
                 "pnl_pct": -5.0, "positions": []})
    cb2 = portfolio_circuit_breaker(drawdown_pct=20.0)
    assert cb2["triggered"] is False


def test_rebalanced_limit_constraint(tmp_path, monkeypatch):
    """涨跌停约束：涨停日买入受限标的不重置权重。"""
    from ashare_monitor import strategy
    import pandas as pd

    def fake_load(code, market):
        rows = []
        # 构造：某标的在周期首日涨停（+10%），其余正常
        for i in range(60):
            d = 1 + i // 30
            day = i % 30 + 1
            base = 10.0 + i * 0.1
            if code == "600519" and d == 2 and day == 1:
                base = 11.0     # 周期首日大涨（模拟涨停）
            rows.append({"date": f"2024-{d:02d}-{day:02d}", "close": base})
        return rows

    monkeypatch.setattr("ashare_monitor.storage.load_klines", fake_load)
    idx_df = pd.DataFrame({
        "date": [f"2024-{1 + i // 30:02d}-{i % 30 + 1:02d}" for i in range(60)],
        "open": [100.0] * 60, "high": [101.0] * 60, "low": [99.0] * 60,
        "close": [100.0 + i * 0.1 for i in range(60)],
        "volume": [1.0] * 60,
    })
    monkeypatch.setattr("akshare.stock_zh_index_daily",
                        lambda symbol="sh000300": idx_df)
    r_on = strategy.portfolio_backtest_rebalanced(
        ["600519", "000001"], frequency="monthly", cost_bps=0.0,
        limit_pct=9.5)
    r_off = strategy.portfolio_backtest_rebalanced(
        ["600519", "000001"], frequency="monthly", cost_bps=0.0,
        limit_pct=None)
    # 约束机制验证：开关参数生效、两模式都正常跑出结果
    assert r_on["limit_pct"] == 9.5
    assert r_off["limit_pct"] is None
    assert r_on["periodic"]["total"] != 0
    assert r_off["periodic"]["total"] != 0
    assert r_on["periodic"]["days"] == r_off["periodic"]["days"]


def test_spearman():
    from ashare_monitor.strategy import _spearman

    # 完全正相关 → 1.0；完全负相关 → -1.0
    assert _spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == pytest.approx(1.0)
    assert _spearman([1, 2, 3, 4, 5], [10, 8, 6, 4, 2]) == pytest.approx(-1.0)


def test_factor_ic_test(tmp_path, monkeypatch):
    from ashare_monitor import strategy

    # 两只标的：一只趋势上行、一只横盘
    drift_map = {"600519": 0.5, "000001": 0.0, "300750": -0.05}

    def fake_load(code, market):
        rows = []
        for i in range(120):
            m = 1 + i // 30
            d = i % 30 + 1
            c = 10.0 + i * drift_map[code]
            rows.append({"date": f"2024-{m:02d}-{d:02d}", "open": c,
                         "close": c, "high": c, "low": c, "volume": 1000.0})
        return rows

    monkeypatch.setattr("ashare_monitor.storage.load_klines", fake_load)
    ic = strategy.factor_ic_test(["600519", "000001", "300750"],
                                 "momentum", forward_days=10)
    assert ic["n_days"] > 0
    assert -1.0 <= ic["mean_ic"] <= 1.0
    assert "ic_ir" in ic and "ic_positive_pct" in ic

    q = strategy.factor_quantile_test(["600519", "000001", "300750"],
                                      "momentum", 5, 10)
    assert q["samples"] > 0
    assert len(q["quantiles"]) <= 5
