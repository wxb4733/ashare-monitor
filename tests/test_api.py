"""Python API 层（OpenBB 模式）单元测试。"""

import pytest


def test_detect_market():
    from ashare_monitor.api import detect_market

    assert detect_market("002594") == "ashare"
    assert detect_market("01211") == "hk"
    assert detect_market("BTCUSDT") == "crypto"
    assert detect_market("ETHUSDT") == "crypto"
    assert detect_market("NVDA") == "us"
    assert detect_market("AAPL") == "us"


def test_quote(monkeypatch):
    import ashare_monitor.api as am

    class _Q:
        code = "002594"
        price = 90.66
        change_pct = 0.21

    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare": ([_Q()], "tencent"))
    q = am.quote("002594")
    assert q.code == "002594"
    assert q.price == pytest.approx(90.66)


def test_quotes_multi_market(monkeypatch):
    import ashare_monitor.api as am

    calls = []

    class _Q:
        def __init__(self, code, price):
            self.code, self.price, self.change_pct = code, price, 0.0

    def fake_fetch(codes, market="ashare"):
        calls.append((codes, market))
        return [_Q(c, 1.0) for c in codes], "mock"

    monkeypatch.setattr("ashare_monitor.quotes.fetch_spot_quotes", fake_fetch)
    qs = am.quotes(["002594", "BTCUSDT"], market=None)
    assert len(qs) == 2
    assert (["002594"], "ashare") in calls
    assert (["BTCUSDT"], "crypto") in calls


def test_kline_and_history(monkeypatch):
    import ashare_monitor.api as am

    rows = [{"date": "2024-01-01", "close": 10.0}] * 30
    monkeypatch.setattr("ashare_monitor.storage.load_klines",
                        lambda code, market: rows)
    assert len(am.kline("002594", days=5)) == 5
    assert len(am.kline("002594")) == 30

    monkeypatch.setattr(
        "ashare_monitor.backfill.analyze_history",
        lambda rows: {"annualized_pct": 45.0, "bars": 30})
    h = am.history("NVDA")
    assert h["annualized_pct"] == pytest.approx(45.0)
    # 无数据时返回提示
    monkeypatch.setattr("ashare_monitor.storage.load_klines",
                        lambda code, market: [])
    assert "note" in am.history("NVDA")


def test_profile_and_check(monkeypatch):
    import ashare_monitor.api as am

    class _Prof:
        status = "OK"
        extra = {"roe": 101.5}

    monkeypatch.setattr("ashare_monitor.asset.build_profile",
                        lambda code, name, market, cfg=None: _Prof())
    p = am.profile("NVDA")
    assert p.extra["roe"] == pytest.approx(101.5)

    monkeypatch.setattr("ashare_monitor.check.check_stock",
                        lambda code, name, market, cfg=None: ["ok"])
    assert am.check("600519") == ["ok"]


def test_screen(monkeypatch):
    import ashare_monitor.api as am

    class _Hit:
        def __init__(self, code):
            self.code = code
            self.name = code

    monkeypatch.setattr("ashare_monitor.screen.screen_dividend",
                        lambda top_n=60, **kw: [_Hit("600519")] * 2)
    hits = am.screen("dividend", top_n=5)
    assert len(hits) == 2

    monkeypatch.setattr("ashare_monitor.screen.screen_us_momentum",
                        lambda top_n=30, **kw: [_Hit("NVDA")])
    assert len(am.screen("momentum", market="us")) == 1

    with pytest.raises(ValueError, match="未知选股指标"):
        am.screen("bad_metric")


def test_factor_ic_and_list(monkeypatch):
    import ashare_monitor.api as am

    monkeypatch.setattr(
        "ashare_monitor.strategy.factor_ic_test",
        lambda codes, factor, forward_days=20: {"mean_ic": 0.04,
                                                "n_days": 100})
    ic = am.factor_ic(["600519"], "momentum", forward=20)
    assert ic["mean_ic"] == pytest.approx(0.04)

    exprs = am.factor_list()
    assert "momentum" in exprs
    assert "(close/Ref(close,20)-1)*100" in exprs["momentum"]


def test_paper_apis(monkeypatch):
    import ashare_monitor.api as am

    monkeypatch.setattr("ashare_monitor.strategy.paper_report",
                        lambda: {"total_value": 100.0, "cash": 50.0})
    rep = am.paper_report()
    assert rep["cash"] == pytest.approx(50.0)

    monkeypatch.setattr("ashare_monitor.strategy.load_paper_positions",
                        lambda: [{"code": "600519"}])
    assert am.paper_positions()[0]["code"] == "600519"

    class _Broker:
        orders = [{"id": 1, "status": "Filled"}]

        @classmethod
        def load(cls):
            return _Broker()

    monkeypatch.setattr("ashare_monitor.broker.PaperBroker", _Broker)
    assert am.paper_orders()[0]["status"] == "Filled"


def test_ad_apis(monkeypatch):
    import ashare_monitor.api as am

    monkeypatch.setattr("ashare_monitor.a_stock_data.tencent_quote_rich",
                        lambda codes: {"600519": {"pe_ttm": 20.0}})
    assert am.ad_quote(["600519"])["600519"]["pe_ttm"] == pytest.approx(20.0)

    monkeypatch.setattr("ashare_monitor.a_stock_data.margin_trading",
                        lambda code: [{"rzye": 1.0e10}])
    assert am.ad_margin("600519")[0]["rzye"] == pytest.approx(1.0e10)
