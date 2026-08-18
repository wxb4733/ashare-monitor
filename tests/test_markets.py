"""港股 / 币安数据源与市场路由单元测试（不依赖网络）。"""

from datetime import datetime

import pytest

from ashare_monitor.main import group_by_market
from ashare_monitor.providers.binance import BinanceProvider, _normalize_symbol
from ashare_monitor.providers.hk import TencentHKProvider
from ashare_monitor.quotes import HK_SESSIONS, fetch_spot_quotes, is_market_open


# ---------- 港股解析 ----------

def make_hk_text() -> str:
    f = ["0"] * 75
    f[0] = "100"             # 每手
    f[1] = "腾讯控股"
    f[2] = "00700"
    f[3] = "443.200"         # 最新价
    f[4] = "446.400"         # 昨收
    f[5] = "444.200"         # 今开
    f[6] = "20288169.0"      # 成交量（股）
    f[30] = "2026/08/18 15:38:13"
    f[31] = "-3.200"         # 涨跌额
    f[32] = "-0.72"          # 涨跌幅
    f[33] = "446.200"        # 最高
    f[34] = "437.600"        # 最低
    f[37] = "9000000000.0"   # 成交额（港元）
    return 'v_r_hk00700="' + "~".join(f) + '";'


def test_hk_parse():
    quotes = TencentHKProvider.parse(make_hk_text())
    assert len(quotes) == 1
    q = quotes[0]
    assert q.code == "00700"
    assert q.name == "腾讯控股"
    assert q.price == 443.2
    assert q.prev_close == 446.4
    assert q.change == -3.2
    assert q.change_pct == -0.72
    assert q.high == 446.2 and q.low == 437.6
    assert q.turnover == 9000000000.0
    assert q.timestamp.hour == 15
    assert q.amplitude == pytest.approx((446.2 - 437.6) / 446.4 * 100, rel=0.01)


def test_hk_parse_garbage_skipped():
    assert TencentHKProvider.parse('v_r_hk00700="1~太短";') == []


# ---------- 币安解析 ----------

def make_binance_ticker() -> dict:
    return {
        "symbol": "BTCUSDT",
        "priceChange": "-1500.00",
        "priceChangePercent": "-1.234",
        "lastPrice": "120000.00",
        "openPrice": "121500.00",
        "highPrice": "122000.00",
        "lowPrice": "119000.00",
        "volume": "1234.567",
        "quoteVolume": "148148148.00",
        "closeTime": 1780000000000,
    }


def test_binance_parse():
    q = BinanceProvider.parse(make_binance_ticker())
    assert q.code == "BTCUSDT"
    assert q.price == 120000.0
    assert q.prev_close == 121500.0
    assert q.change == -1500.0
    assert q.change_pct == -1.234
    assert q.volume == 1234.567
    assert q.turnover == 148148148.0
    assert q.amplitude == pytest.approx(
        (122000.0 - 119000.0) / 121500.0 * 100, rel=0.01
    )


def test_normalize_symbol():
    assert _normalize_symbol("btc-usdt") == "BTCUSDT"
    assert _normalize_symbol("ETH/USDC") == "ETHUSDC"
    assert _normalize_symbol("SOLUSDT") == "SOLUSDT"


# ---------- 市场路由与交易时段 ----------

def test_group_by_market():
    watchlist = [
        {"code": "600519"},
        {"code": "00700", "market": "hk"},
        {"code": "BTCUSDT", "market": "crypto"},
        {"code": "000001", "market": "ashare"},
    ]
    groups = group_by_market(watchlist)
    assert groups == {
        "ashare": ["600519", "000001"],
        "hk": ["00700"],
        "crypto": ["BTCUSDT"],
    }


def test_is_market_open():
    t = datetime(2026, 8, 17, 15, 30)   # 周一 15:30：A 股已收盘，港股盘中
    assert not is_market_open("ashare", [["09:30", "11:30"], ["13:00", "15:00"]], t)
    assert is_market_open("hk", now=t)
    assert is_market_open("crypto", now=t)          # 7×24
    # 港股 16:00 收盘
    assert not is_market_open("hk", now=datetime(2026, 8, 17, 16, 30))
    # 港股午休（12:00-13:00）也闭市
    assert not is_market_open("hk", now=datetime(2026, 8, 17, 12, 30))
    # 周末港股闭市，币安不休
    sat = datetime(2026, 8, 15, 10, 0)
    assert not is_market_open("hk", now=sat)
    assert is_market_open("crypto", now=sat)
    assert HK_SESSIONS == [["09:30", "12:00"], ["13:00", "16:00"]]


def test_fetch_market_default_chain(monkeypatch):
    """不指定 sources 时，按 market 使用对应默认数据源链。"""
    from ashare_monitor.providers import PROVIDERS

    called = []

    class _SpyHK:
        name = "tencent_hk"

        def fetch(self, codes):
            called.append(("tencent_hk", codes))
            return ["hk-quote"]

    class _SpyBinance:
        name = "binance"

        def fetch(self, codes):
            called.append(("binance", codes))
            return ["crypto-quote"]

    monkeypatch.setitem(PROVIDERS, "tencent_hk", _SpyHK)
    monkeypatch.setitem(PROVIDERS, "binance", _SpyBinance)

    quotes, source = fetch_spot_quotes(["00700"], market="hk")
    assert source == "tencent_hk" and quotes == ["hk-quote"]
    quotes, source = fetch_spot_quotes(["BTCUSDT"], market="crypto")
    assert source == "binance" and quotes == ["crypto-quote"]
