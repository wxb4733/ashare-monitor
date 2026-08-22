"""CoinGecko 历史补充单元测试。"""

import datetime as dt

import pytest


def test_backfill_kline_coingecko(monkeypatch):
    from ashare_monitor.backfill import _backfill_kline_coingecko

    base = dt.datetime(2015, 8, 7, tzinfo=dt.timezone.utc)
    prices = [[int((base + dt.timedelta(days=i)).timestamp() * 1000),
               1.0 + i / 10] for i in range(20)]

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"prices": prices}

    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
    rows = _backfill_kline_coingecko("ETHUSDT", "2017-08-01")
    assert len(rows) == 20
    assert rows[0][0] == "2015-08-07"      # ETH 上线日
    # OHLC 收盘近似，volume 0（如实）
    assert rows[0][1] == rows[0][2] == rows[0][3] == rows[0][4]
    assert rows[0][5] == 0.0


def test_backfill_kline_coingecko_cutoff(monkeypatch):
    from ashare_monitor.backfill import _backfill_kline_coingecko

    base = dt.datetime(2015, 8, 7, tzinfo=dt.timezone.utc)
    prices = [[int((base + dt.timedelta(days=i)).timestamp() * 1000), 1.0]
              for i in range(5)]

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"prices": prices}

    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
    rows = _backfill_kline_coingecko("ETHUSDT", "2015-08-09")
    assert len(rows) == 2
    assert rows[-1][0] == "2015-08-08"


def test_coingecko_id_mapping():
    from ashare_monitor.backfill import _COINGECKO_IDS

    assert _COINGECKO_IDS["BTCUSDT"] == "bitcoin"
    assert _COINGECKO_IDS["ETHUSDT"] == "ethereum"
    assert _COINGECKO_IDS.get("DOGEUSDT") is None   # 未映射币不补
