"""多行情源 Provider 单元测试（解析逻辑 + 降级链）。"""

import pytest

from ashare_monitor.providers.base import QuoteProvider, get_market_prefix
from ashare_monitor.providers.sina import SinaProvider
from ashare_monitor.providers.tencent import TencentProvider
from ashare_monitor.quotes import fetch_spot_quotes


# ---------- 市场前缀规则 ----------

def test_market_prefix():
    assert get_market_prefix("600519") == "sh"
    assert get_market_prefix("000001") == "sz"
    assert get_market_prefix("300750") == "sz"
    assert get_market_prefix("430139") == "bj"
    assert get_market_prefix("sz000001") == "sz"


# ---------- 新浪解析 ----------

def make_sina_text() -> str:
    # 名称后 29 个数值：9 个基础字段 + 10 个买盘 + 10 个卖盘
    fields = [
        "1690.000", "1690.000", "1705.000", "1710.000", "1680.000",
        "1705.000", "1706.000", "123456700", "2100000000.000",
    ] + [f"{i}.000" for i in range(20)]
    return (
        'var hq_str_sh600519="贵州茅台,'
        + ",".join(fields)
        + ',2026-08-18,09:35:00";'
    )


def test_sina_parse():
    quotes = SinaProvider.parse(make_sina_text())
    assert len(quotes) == 1
    q = quotes[0]
    assert q.code == "600519"
    assert q.name == "贵州茅台"
    assert q.price == 1705.0
    assert q.prev_close == 1690.0
    assert q.change == pytest.approx(15.0)
    assert q.change_pct == pytest.approx(0.89, abs=0.01)
    assert q.volume == 1234567.0          # 股 → 手
    assert q.turnover == 2100000000.0
    assert q.timestamp.hour == 9 and q.timestamp.minute == 35


def test_sina_parse_empty_returns_nothing():
    assert SinaProvider.parse('var hq_str_sh600519="";') == []


# ---------- 腾讯解析 ----------

def make_tencent_text() -> str:
    f = ["0"] * 54
    f[0] = 'v_sh600519="1'
    f[1] = "贵州茅台"
    f[2] = "600519"
    f[3] = "1705.00"      # 最新价
    f[4] = "1690.00"      # 昨收
    f[5] = "1695.00"      # 今开
    f[30] = "20260818093500"
    f[31] = "15.00"       # 涨跌额
    f[32] = "0.89"        # 涨跌幅
    f[33] = "1710.00"     # 最高
    f[34] = "1680.00"     # 最低
    f[36] = "1234567"     # 成交量（手）
    f[37] = "210000.00"   # 成交额（万）
    return "~".join(f) + '";'


def test_tencent_parse():
    quotes = TencentProvider.parse(make_tencent_text())
    assert len(quotes) == 1
    q = quotes[0]
    assert q.code == "600519"
    assert q.price == 1705.0
    assert q.change == 15.0
    assert q.change_pct == 0.89
    assert q.volume == 1234567
    assert q.turnover == 210000.0 * 10000
    assert q.timestamp.year == 2026


def test_tencent_parse_short_record_skipped():
    assert TencentProvider.parse('v_sh600519="1~太短";') == []


# ---------- 降级链 ----------

class _FailProvider(QuoteProvider):
    name = "fail"

    def fetch(self, codes):
        raise ConnectionError("boom")


class _EmptyProvider(QuoteProvider):
    name = "empty"

    def fetch(self, codes):
        return []


class _OkProvider(QuoteProvider):
    name = "ok"

    def fetch(self, codes):
        return ["fake-quote"]


def test_fetch_fallback_order(monkeypatch):
    from ashare_monitor.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, "fail", _FailProvider)
    monkeypatch.setitem(PROVIDERS, "empty", _EmptyProvider)
    monkeypatch.setitem(PROVIDERS, "ok", _OkProvider)

    quotes, source = fetch_spot_quotes(
        ["600519"], sources=["fail", "empty", "ok"]
    )
    assert quotes == ["fake-quote"]
    assert source == "ok"


def test_fetch_all_sources_fail_raises(monkeypatch):
    from ashare_monitor.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS, "fail", _FailProvider)
    with pytest.raises(RuntimeError, match="所有行情数据源均不可用"):
        fetch_spot_quotes(["600519"], sources=["fail", "fail"])
