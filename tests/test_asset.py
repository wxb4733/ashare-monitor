"""资产画像统一接口（AssetProfile）单元测试。"""

import pytest


def test_stock_profile(monkeypatch):
    from ashare_monitor.asset import stock_profile

    monkeypatch.setattr(
        "ashare_monitor.fundamentals.fetch_financials",
        lambda code, periods=2, market="ashare": [type("F", (), {
            "roe": 18.5, "profit_yoy": 12.3, "report_date": "2026-06-30",
            "gross_margin": 30.0, "net_margin": 15.0})()])
    monkeypatch.setattr(
        "ashare_monitor.valuation.fetch_valuation",
        lambda code, years=5: type("V", (), {
            "pe_ttm": 29.9, "pe_pct": 48.0, "pb_mrq": 3.56, "pb_pct": 3.0,
            "close": 90.0})())
    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare": ([type("Q", (), {
            "price": 90.0, "market_cap": 2.6e12,
            "change_pct": 1.5})()], "tencent"))
    monkeypatch.setattr(
        "ashare_monitor.dividend.load_dividend_history",
        lambda code: [type("D", (), {"yield_pct": 1.2})()])

    p = stock_profile("002594", "比亚迪", "ashare")
    assert p.status == "OK"
    assert p.growth_rate == pytest.approx(12.3)
    assert p.extra["roe"] == pytest.approx(18.5)
    assert p.valuation["pe_ttm"] == pytest.approx(29.9)
    assert p.yield_rate == pytest.approx(1.2)
    assert p.extra["price"] == pytest.approx(90.0)


def test_crypto_profile_placeholder():
    from ashare_monitor.asset import crypto_profile

    p = crypto_profile("BTC", "Bitcoin")
    assert p.market == "crypto"
    # 沙箱境外 API 不可达 → 走失败降级（WARN + 本机提示）
    assert p.status == "WARN"
    assert p.note


def test_crypto_profile_mapping(monkeypatch):
    from ashare_monitor.asset import crypto_profile

    def fake_get(url, params, headers, timeout=15):
        class R:
            def json(self):
                return [{
                    "id": "bitcoin", "symbol": "btc",
                    "current_price": 77206.19, "market_cap": 1.52e12,
                    "total_supply": 21000000.0,
                    "circulating_supply": 19700000.0,
                    "total_volume": 5.0e10,
                    "price_change_percentage_24h": 0.42, "ath": 100000.0,
                    "ath_change_percentage": -22.8,
                }]
        return R()

    monkeypatch.setattr("requests.get", fake_get)
    p = crypto_profile("BTCUSDT")   # 交易对自动映射 bitcoin
    assert p.status == "OK"
    assert p.market_cap == pytest.approx(1.52e12)
    assert p.supply_total == pytest.approx(21000000.0)
    # 流通/总量 = 19.7/21 = 93.8%
    assert p.growth_rate == pytest.approx(93.81, abs=0.1)
    # NVT ≈ 1.52e12 / 5e10 = 30.4
    assert p.valuation["nvt_approx"] == pytest.approx(30.4, abs=0.5)
    assert p.yield_rate is None  # 质押收益 CoinGecko 基础接口无（如实）


def test_crypto_profile_fallback(monkeypatch):
    from ashare_monitor.asset import crypto_profile

    def fake_get(url, params, headers, timeout=15):
        raise RuntimeError("connect timeout")

    monkeypatch.setattr("requests.get", fake_get)
    p = crypto_profile("BTC")
    assert p.status == "WARN"
    assert "本机直连" in p.note


def test_build_profile_dispatch(monkeypatch):
    from ashare_monitor.asset import build_profile, crypto_profile, stock_profile

    monkeypatch.setattr("ashare_monitor.asset.stock_profile",
                        lambda code, name, market, cfg=None: "STOCK")
    monkeypatch.setattr("ashare_monitor.asset.crypto_profile",
                        lambda code, name: "CRYPTO")
    assert build_profile("600519", "茅台", "ashare") == "STOCK"
    assert build_profile("BTC", "Bitcoin", "crypto") == "CRYPTO"
