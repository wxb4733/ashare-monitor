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


def test_record_paper_nav_skips_when_valuation_unavailable(monkeypatch, tmp_path):
    """行情不可用（估值退化为 0）时不得写入净值，避免 -100% 污染曲线。

    回归背景：2026-10-16 盘前 09:20 的 risk-check 任务跑 strategy track，
    拿不到行情 → 写入 0 元 / -100% 净值。
    """
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = tmp_path / "p.db"
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    monkeypatch.setattr(
        "ashare_monitor.strategy.paper_report",
        lambda: {"total_value": 0.0, "total_cost": 94_266.0,
                 "pnl_pct": -100.0, "positions": []})

    rec = strategy.record_paper_nav()
    assert rec["skipped"] is True
    assert strategy.load_paper_nav() == []


def test_record_paper_nav_skips_when_quotes_stale(monkeypatch, tmp_path):
    """行情日期 ≠ 今日（休市/停更）时不得写入净值。

    回归背景：2026-10-01~10-07 国庆休市期间，spot 接口返回上一交易日快照，
    旧逻辑照写 → paper_history 多出 5 行走平假净值（2026-10-19 清理）。
    """
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = tmp_path / "p_stale.db"
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    monkeypatch.setattr(
        "ashare_monitor.strategy.paper_report",
        lambda: {"total_value": 100_513.0, "total_cost": 94_266.0,
                 "pnl_pct": 6.63,
                 "positions": [{"code": "601398",
                                "quote_date": "2026-10-07"}]})

    rec = strategy.record_paper_nav()
    assert rec["skipped"] is True
    assert "非今日" in rec["reason"]
    assert strategy.load_paper_nav() == []


def test_record_paper_nav_writes_when_quotes_fresh(monkeypatch, tmp_path):
    """行情日期为今日时正常写入（护栏不得误伤正常收盘后记录）。"""
    import datetime as _dt

    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = tmp_path / "p_fresh.db"
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(
        "ashare_monitor.strategy.paper_report",
        lambda: {"total_value": 100_513.0, "total_cost": 94_266.0,
                 "pnl_pct": 6.63,
                 "positions": [{"code": "601398", "quote_date": today}]})

    rec = strategy.record_paper_nav()
    assert not rec.get("skipped")
    navs = strategy.load_paper_nav()
    assert len(navs) == 1
    assert navs[0]["date"] == today


def _seed_klines(db, rows):
    """建最小 klines 表并插入 (code, date, close)。"""
    import sqlite3
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS klines ("
                     "market TEXT, code TEXT, date TEXT, close REAL)")
        conn.executemany(
            "INSERT INTO klines (market, code, date, close) VALUES ('ashare',?,?,?)",
            rows)
    conn.close()


def test_record_paper_nav_backfills_history_from_klines(monkeypatch, tmp_path):
    """as_of 补录模式：按库内该日收盘价离线估值，绕过「行情日期≠今日」护栏。

    回归背景：2026-10-19 15:45 paper-daily 因 bat 行尾被写成 LF 导致
    strategy track 解析失败，当日净值漏写；spot 快照只能取最新交易日，
    历史日期必须用已入库 K 线估值补录。
    """
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "backfill.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    _seed_klines(db, [("000001", "2026-10-19", 11.0),
                      ("000001", "2026-10-16", 10.5)])
    monkeypatch.setattr(
        "ashare_monitor.strategy.load_paper_positions",
        lambda: [{"code": "000001", "name": "平安银行", "shares": 10000,
                  "avg_cost": 10.0}])

    class _Broker:
        cash = 5000.0

    monkeypatch.setattr("ashare_monitor.broker.PaperBroker.load",
                        classmethod(lambda cls: _Broker()))

    rec = strategy.record_paper_nav(as_of="2026-10-19")
    assert not rec.get("skipped"), rec.get("reason")
    assert rec["date"] == "2026-10-19"
    assert rec["total_value"] == pytest.approx(110_000.0)
    assert rec["pnl_pct"] == pytest.approx(10.0)
    navs = strategy.load_paper_nav()
    assert [n["date"] for n in navs] == ["2026-10-19"]
    assert navs[0]["nav"] == pytest.approx(1.1)


def test_record_paper_nav_backfill_skips_when_kline_missing(monkeypatch, tmp_path):
    """任一持仓缺该日收盘价时跳过（避免写入偏低失真净值）。"""
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "backfill_gap.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    _seed_klines(db, [("000001", "2026-10-19", 11.0)])   # 缺 601398
    monkeypatch.setattr(
        "ashare_monitor.strategy.load_paper_positions",
        lambda: [{"code": "000001", "name": "平安银行", "shares": 1000,
                  "avg_cost": 10.0},
                 {"code": "601398", "name": "工商银行", "shares": 1000,
                  "avg_cost": 5.0}])

    rec = strategy.record_paper_nav(as_of="2026-10-19")
    assert rec["skipped"] is True
    assert "601398" in rec["reason"]
    assert strategy.load_paper_nav() == []


def test_record_paper_nav_backfill_rejects_today(monkeypatch):
    """补录日期须早于今日（当日应走实时 track）。"""
    import datetime as _dt

    from ashare_monitor import strategy

    today = _dt.datetime.now().strftime("%Y-%m-%d")
    rec = strategy.record_paper_nav(as_of=today)
    assert rec["skipped"] is True
    assert "须早于今日" in rec["reason"]


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


def test_rebalance_orders_clears_position_without_lot_dust(monkeypatch):
    """清仓整手不能被浮点地板截断（2026-11-01 调仓首跑 5 只各残留 100 股）。

    1800 股 × 5.90 的目标差额是整 1800 股，但 ``10620.0 // 5.9 // 100`` 在
    浮点下得 17 手 → 只卖 1700，留 100 股零头占仓。
    """
    from ashare_monitor import strategy

    monkeypatch.setattr(
        "ashare_monitor.strategy.load_paper_positions",
        lambda: [{"code": "600028", "name": "中国石化", "shares": 1800,
                  "avg_cost": 5.32, "updated": "2026-09-26"}])

    class _Q:
        code = "600028"
        price = 5.90

    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare": ([_Q()], "tencent"))
    # 空目标 → 清仓（f133 新榜首无中国石化）
    orders = strategy.rebalance_orders([], 100_000.0)
    sell = [o for o in orders if o["code"] == "600028"][0]
    assert sell["side"] == "sell" and sell["reason"] == "清仓"
    assert sell["shares"] == 1800          # 不是 1700


def test_execute_rebalance_does_not_inject_capital_again(monkeypatch, tmp_path):
    """月度再平衡不得重复注入本金（2026-11-01 首跑净资产 103,415→209,125）。

    ``cash`` 参数语义是"空账户建仓本金"，已有持仓的账户应只用现有现金 +
    卖出回款，否则每次调仓净资产翻倍、次日 track 写出 +100% 假净值。
    """
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "rebalance.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))

    from ashare_monitor.broker import PaperBroker

    broker = PaperBroker(cash=5_492.43)
    broker.positions = {"600028": {"code": "600028", "name": "中国石化",
                                   "shares": 1800, "avg_cost": 5.32}}
    monkeypatch.setattr("ashare_monitor.broker.PaperBroker.load",
                        classmethod(lambda cls: broker))

    orders = [{"code": "600028", "name": "中国石化", "side": "sell",
               "shares": 1800, "price": 5.90, "value": 10_620.0,
               "reason": "清仓"}]
    result = strategy.execute_rebalance(orders, cash=100_000.0)
    # 现金 = 5,492.43 + 1,800×5.90（无佣金/印花税），本金未被二次注入
    assert broker.cash == pytest.approx(5_492.43 + 10_620.0)
    assert result["cash"] == pytest.approx(broker.cash, rel=1e-6)
    assert "600028" not in broker.positions


def test_record_paper_nav_uses_equity_over_initial_capital(monkeypatch, tmp_path):
    """净值口径统一：(持仓市值+现金)/初始本金，成本基数不再随调仓重置。

    回归背景：旧口径 nav = 市值/持仓成本，11-01 调仓把成本基数 94,266 →
    102,998，11-02 nav 从 1.0971 断崖到 1.0005（并非亏损）；且旧口径不含
    现金 5,492.43，真实权益被低估。
    """
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "nav_scope.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    import datetime as _dt

    today = _dt.datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(
        "ashare_monitor.strategy.paper_report",
        lambda: {"total_value": 104_860.0, "total_cost": 102_998.0,
                 "cash": 5_492.43, "equity": 110_352.43,
                 "pnl_pct": 1.81,
                 "positions": [{"code": "601398", "quote_date": today}]})

    rec = strategy.record_paper_nav()
    assert not rec.get("skipped")
    navs = strategy.load_paper_nav()
    assert len(navs) == 1
    row = navs[0]
    assert row["value"] == pytest.approx(110_352.43)   # 总权益，非持仓市值
    assert row["cost"] == pytest.approx(100_000.0)     # 初始本金，非持仓成本
    assert row["nav"] == pytest.approx(1.1035243)
    assert row["pnl_pct"] == pytest.approx(10.35, abs=0.01)


def test_paper_cash_on_reconstructs_from_orders(monkeypatch, tmp_path):
    """历史现金按 paper_orders 流水反推：本金 − Σ(买+费) + Σ(卖−费)。

    回归背景：补录历史净值时 paper_account 只有当前现金；11-01 调仓前
    现金是 5,710.44（含建仓费），直接用当前值会失真。
    """
    import sqlite3

    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "cash.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    conn = sqlite3.connect(db)
    with conn:
        conn.execute(
            "CREATE TABLE paper_orders (id INTEGER PRIMARY KEY, code TEXT, "
            "name TEXT, side TEXT, shares REAL, price REAL, fee REAL, "
            "status TEXT, reason TEXT, created TEXT, updated TEXT)")
        conn.executemany(
            "INSERT INTO paper_orders (code, name, side, shares, price, fee,"
            " status, reason, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [("601398", "工商银行", "buy", 1000, 8.0, 2.0, "Filled", "新进",
              "2026-09-26 14:13:16", "2026-09-26 14:13:16"),
             ("600028", "中国石化", "sell", 1000, 5.9, 1.5, "Filled", "清仓",
              "2026-11-01 15:45:00", "2026-11-01 15:45:00")])
    conn.close()
    # 调仓前：现金 = 100000 − (8000+2)
    assert strategy._paper_cash_on("2026-10-30") == pytest.approx(91_998.0)
    # 调仓后：+ (5900−1.5)
    assert strategy._paper_cash_on("2026-11-01") == pytest.approx(97_896.5)
    # 无 paper_orders 表（全新库）→ 返回 0，不抛异常
    assert strategy._paper_cash_on.__name__ == "_paper_cash_on"


def _mk_quote(**kw):
    """构造最小 Quote（rebalance_orders 涨跌停判定用）。"""
    from ashare_monitor.quotes import Quote
    from datetime import datetime

    base = dict(code="000915", name="华特达因", price=21.42, change_pct=-10.0,
                change=-2.38, volume=13615.0, turnover=0.0, high=21.42,
                low=21.42, open=21.42, prev_close=23.80,
                timestamp=datetime(2026, 10, 30, 15, 0))
    base.update(kw)
    return Quote(**base)


def test_limit_locked_detects_one_word_limit_down():
    """一字跌停判定：2026-10-30 华特达因开=高=低=收=21.42（-10%）。"""
    from ashare_monitor.strategy import _limit_locked

    assert _limit_locked(_mk_quote()) == "limit_down"
    # 一字涨停
    assert _limit_locked(_mk_quote(price=26.18, open=26.18, high=26.18,
                                   low=26.18, change_pct=10.0,
                                   prev_close=23.80)) == "limit_up"
    # 非一字（有波动）→ None
    assert _limit_locked(_mk_quote(high=22.0, low=21.0)) is None
    # 创业板 20% 板
    assert _limit_locked(_mk_quote(code="300770", prev_close=40.56,
                                   price=36.50, change_pct=-10.0)) is None
    assert _limit_locked(_mk_quote(code="300770", prev_close=40.56,
                                   price=32.44, change_pct=-20.02,
                                   open=32.44, high=32.44,
                                   low=32.44)) == "limit_down"


def test_rebalance_orders_skips_limit_down_buy(monkeypatch, tmp_path):
    """买入目标为一字跌停时不得假装成交：指令降级为 hold 顺延。"""
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "rebal_ld.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))

    monkeypatch.setattr("ashare_monitor.strategy.load_paper_positions",
                        lambda: [])
    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare":
            ([_mk_quote()], "tencent"))
    targets = [strategy.TargetPosition("000915", "华特达因", 10.0, 10_000.0)]
    orders = strategy.rebalance_orders(targets, 100_000.0)
    assert len(orders) == 1
    o = orders[0]
    assert o["side"] == "hold"
    assert o["shares"] == 0
    assert "一字跌停" in o["reason"]


def test_rebalance_orders_skips_recent_crash_buy(monkeypatch, tmp_path):
    """近5日跌幅≥15% 的新进买入顺延（股息率陷阱防护）。"""
    import sqlite3

    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "rebal_crash.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("CREATE TABLE klines (market TEXT, code TEXT, "
                     "date TEXT, close REAL)")
        # 近5日 25.00 → 21.00（-16%，未一字跌停）
        for i, c in enumerate([25.0, 24.5, 23.5, 22.5, 21.8, 21.0]):
            conn.execute("INSERT INTO klines VALUES ('ashare','000915',?,?)",
                         (f"2026-10-{20+i:02d}", c))
    conn.close()

    monkeypatch.setattr("ashare_monitor.strategy.load_paper_positions",
                        lambda: [])
    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare":
            ([_mk_quote(price=21.0, open=21.2, high=21.5, low=20.8,
                        change_pct=-3.64, prev_close=21.8)], "tencent"))
    targets = [strategy.TargetPosition("000915", "华特达因", 10.0, 10_000.0)]
    orders = strategy.rebalance_orders(targets, 100_000.0)
    assert len(orders) == 1
    o = orders[0]
    assert o["side"] == "hold"
    assert "股息率陷阱" in o["reason"]


def _mk_quote(**kw):
    """构造最小 Quote（rebalance_orders 涨跌停判定用）。"""
    from ashare_monitor.quotes import Quote
    from datetime import datetime

    base = dict(code="000915", name="华特达因", price=21.42, change_pct=-10.0,
                change=-2.38, volume=13615.0, turnover=0.0, high=21.42,
                low=21.42, open=21.42, prev_close=23.80,
                timestamp=datetime(2026, 10, 30, 15, 0))
    base.update(kw)
    return Quote(**base)


def test_limit_locked_detects_one_word_limit_down():
    """一字跌停判定：2026-10-30 华特达因开=高=低=收=21.42（-10%）。"""
    from ashare_monitor.strategy import _limit_locked

    assert _limit_locked(_mk_quote()) == "limit_down"
    # 一字涨停
    assert _limit_locked(_mk_quote(price=26.18, open=26.18, high=26.18,
                                   low=26.18, change_pct=10.0,
                                   prev_close=23.80)) == "limit_up"
    # 非一字（有波动）→ None
    assert _limit_locked(_mk_quote(high=22.0, low=21.0)) is None
    # 创业板 20% 板
    assert _limit_locked(_mk_quote(code="300770", prev_close=40.56,
                                   price=36.50, change_pct=-10.0)) is None
    assert _limit_locked(_mk_quote(code="300770", prev_close=40.56,
                                   price=32.44, change_pct=-20.02,
                                   open=32.44, high=32.44,
                                   low=32.44)) == "limit_down"


def test_rebalance_orders_skips_limit_down_buy(monkeypatch, tmp_path):
    """买入目标为一字跌停时不得假装成交：指令降级为 hold 顺延。"""
    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "rebal_ld.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))

    monkeypatch.setattr("ashare_monitor.strategy.load_paper_positions",
                        lambda: [])
    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare":
            ([_mk_quote()], "tencent"))
    targets = [strategy.TargetPosition("000915", "华特达因", 10.0, 10_000.0)]
    orders = strategy.rebalance_orders(targets, 100_000.0)
    assert len(orders) == 1
    o = orders[0]
    assert o["side"] == "hold"
    assert o["shares"] == 0
    assert "一字跌停" in o["reason"]


def test_rebalance_orders_skips_recent_crash_buy(monkeypatch, tmp_path):
    """近5日跌幅≥15% 的新进买入顺延（股息率陷阱防护）。"""
    import sqlite3

    from ashare_monitor import strategy
    import ashare_monitor.storage as storage

    db = str(tmp_path / "rebal_crash.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("CREATE TABLE klines (market TEXT, code TEXT, "
                     "date TEXT, close REAL)")
        # 近5日 25.00 → 21.00（-16%，未一字跌停）
        for i, c in enumerate([25.0, 24.5, 23.5, 22.5, 21.8, 21.0]):
            conn.execute("INSERT INTO klines VALUES ('ashare','000915',?,?)",
                         (f"2026-10-{20+i:02d}", c))
    conn.close()

    monkeypatch.setattr("ashare_monitor.strategy.load_paper_positions",
                        lambda: [])
    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare":
            ([_mk_quote(price=21.0, open=21.2, high=21.5, low=20.8,
                        change_pct=-3.64, prev_close=21.8)], "tencent"))
    targets = [strategy.TargetPosition("000915", "华特达因", 10.0, 10_000.0)]
    orders = strategy.rebalance_orders(targets, 100_000.0)
    assert len(orders) == 1
    o = orders[0]
    assert o["side"] == "hold"
    assert "股息率陷阱" in o["reason"]
