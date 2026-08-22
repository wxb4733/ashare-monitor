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
    assert p.status == "WARN"
    assert "Phase 2" in p.note


def test_build_profile_dispatch(monkeypatch):
    from ashare_monitor.asset import build_profile, crypto_profile, stock_profile

    monkeypatch.setattr("ashare_monitor.asset.stock_profile",
                        lambda code, name, market, cfg=None: "STOCK")
    monkeypatch.setattr("ashare_monitor.asset.crypto_profile",
                        lambda code, name: "CRYPTO")
    assert build_profile("600519", "茅台", "ashare") == "STOCK"
    assert build_profile("BTC", "Bitcoin", "crypto") == "CRYPTO"
