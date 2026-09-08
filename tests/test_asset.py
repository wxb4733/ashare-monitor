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


def test_us_profile_sec_local_first(monkeypatch):
    """本地 SEC 落库优先：ROE/增速/毛利率来自 financials（权威），不触网。"""
    from ashare_monitor.asset import us_profile

    sec_rows = [{
        "report_date": "2026-01-25", "revenue": 2159.38, "net_profit": 1200.67,
        "revenue_yoy": 65.47, "profit_yoy": 64.75, "roe": 76.33,
        "gross_margin": 71.07, "net_margin": 55.6, "eps": 4.9,
        "ocf_per_share": None, "currency": "USD",
    }]
    # akshare 若被误调应抛错（SEC 路径不应触网）
    monkeypatch.setattr(
        "akshare.stock_financial_us_analysis_indicator_em",
        lambda symbol, indicator="年报": (_ for _ in ()).throw(
            RuntimeError("should not touch akshare")))
    monkeypatch.setattr("ashare_monitor.storage.load_financials",
                        lambda code, **kw: sec_rows)
    p = us_profile("NVDA", "英伟达")
    assert p.status == "OK"
    assert p.extra["roe"] == pytest.approx(76.33)
    assert p.growth_rate == pytest.approx(64.75)
    assert p.extra["gross_margin"] == pytest.approx(71.07)
    assert p.extra["data_source"] == "SEC"
    assert p.extra["currency"] == "USD"
    # 金额口径 = 币种元（亿美元 ×1e8 → 美元元），供 PE≈市值/净利 复用
    assert p.extra["net_profit"] == pytest.approx(1200.67e8)
    assert p.extra["revenue"] == pytest.approx(2159.38e8)


def test_us_profile_local_empty_falls_to_akshare(monkeypatch):
    """本地无 SEC 数据 → akshare 东财兜底（实时源）。"""
    import pandas as pd

    from ashare_monitor.asset import us_profile

    monkeypatch.setattr("ashare_monitor.storage.load_financials",
                        lambda code, **kw: [])
    df = pd.DataFrame([{
        "REPORT_DATE": "2026-01-31", "ROE_AVG": 101.5,
        "PARENT_HOLDER_NETPROFIT_YOY": 64.7,
        "GROSS_PROFIT_RATIO": 71.1, "BASIC_EPS": 3.6,
        "OPERATE_INCOME": 1.3e11, "PARENT_HOLDER_NETPROFIT": 6.0e10,
    }])
    monkeypatch.setattr(
        "akshare.stock_financial_us_analysis_indicator_em",
        lambda symbol, indicator="年报": df)
    p = us_profile("SOME_NEW", "新标的")
    assert p.status == "OK"
    assert p.extra["roe"] == pytest.approx(101.5)
    assert p.extra["data_source"] == "eastmoney"
    assert p.note.startswith("东财")


def test_us_profile_fallback(monkeypatch):
    """本地空 + akshare 失败 → WARN（如实）。"""
    from ashare_monitor.asset import us_profile

    monkeypatch.setattr("ashare_monitor.storage.load_financials",
                        lambda code, **kw: [])
    monkeypatch.setattr(
        "akshare.stock_financial_us_analysis_indicator_em",
        lambda symbol, indicator="年报": (_ for _ in ()).throw(
            RuntimeError("net down")))
    p = us_profile("NVDA")
    assert p.status == "WARN"


def test_fetch_onchain_btc(monkeypatch):
    """BTC 通胀率：近 1 年新增供给/总量。"""
    from ashare_monitor.asset import fetch_onchain_profile

    class _R:
        def json(self):
            # 1950 万 → 1985 万（年增 35 万 → 通胀 ~1.76%）
            return {"values": [{"y": 1.95e7}, {"y": 1.985e7}]}

    monkeypatch.setattr("requests.get",
                        lambda *a, **k: _R())
    r = fetch_onchain_profile("BTCUSDT")
    assert r["inflation_pct"] == pytest.approx(1.76, abs=0.1)
    assert "blockchain.info" in r["note"]


def test_fetch_onchain_eth(monkeypatch):
    """ETH 质押收益：Lido stETH APR。"""
    from ashare_monitor.asset import fetch_onchain_profile

    class _R:
        def json(self):
            return {"data": {"apr": 0.0312}}

    monkeypatch.setattr("requests.get",
                        lambda *a, **k: _R())
    r = fetch_onchain_profile("ETHUSDT")
    assert r["staking_yield_pct"] == pytest.approx(3.12, abs=0.01)
    assert "Lido" in r["note"]


def test_fetch_onchain_fallback(monkeypatch):
    """境外不可达 → 字段 None + 本机提示（如实）。"""
    from ashare_monitor.asset import fetch_onchain_profile

    def _boom(*a, **k):
        raise RuntimeError("connect timeout")

    monkeypatch.setattr("requests.get", _boom)
    r = fetch_onchain_profile("BTCUSDT")
    assert r["inflation_pct"] is None
    assert "本机直连" in r["note"]
