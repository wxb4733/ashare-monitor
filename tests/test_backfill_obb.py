"""OpenBB(yfinance) K 线降级源单元测试（全程 mock，不触网）。"""

import pandas as pd
import pytest

from ashare_monitor.backfill import _backfill_kline_obb


# ---------- 工具 ----------

def _fake_res(df):
    """伪装 OBBject：仅暴露 to_dataframe()。"""

    class _Res:
        def to_dataframe(self):
            return df

    return _Res()


def _fake_df() -> pd.DataFrame:
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame({
        "open": [100.0, 102.0, 101.0],
        "high": [105.0, 104.0, 103.0],
        "low": [99.0, 100.5, 100.0],
        "close": [102.5, 101.0, 102.0],
        "volume": [1000.0, 1200.0, 1100.0],
    }, index=idx)


def _patch_hist(monkeypatch, fake):
    """替换 _obb_historical 薄封装（OpenBB Router 实例不可 setattr，走模块级 patch）。"""
    from ashare_monitor import backfill as bf

    monkeypatch.setattr(bf, "_obb_historical",
                        lambda symbol, start, end: fake)


# ---------- _backfill_kline_obb 行映射 ----------

def test_obb_maps_rows_standard(monkeypatch):
    _patch_hist(monkeypatch, _fake_res(_fake_df()))
    rows = _backfill_kline_obb("NVDA", "us", "2024-01-01")
    assert len(rows) == 3
    # (date, open, close, high, low, volume)——与 record_klines 口径一致
    assert rows[0] == ("2024-01-02", 100.0, 102.5, 105.0, 99.0, 1000.0)
    assert rows[-1][0] == "2024-01-04"
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)


def test_obb_maps_hk_symbol(monkeypatch):
    """港股 01211 → yfinance 代码 1211.HK。"""
    from ashare_monitor import backfill as bf

    seen = {}

    def fake_hist(symbol, start, end):
        seen["symbol"] = symbol
        return _fake_res(_fake_df())

    monkeypatch.setattr(bf, "_obb_historical", fake_hist)
    _backfill_kline_obb("01211", "hk", "2002-01-01")
    assert seen["symbol"] == "1211.HK"


def test_obb_tolerates_uppercase_columns(monkeypatch):
    """provider 返回大写列名时容错（小写归一）。"""
    df = _fake_df().rename(columns=str.upper)
    _patch_hist(monkeypatch, _fake_res(df))
    rows = _backfill_kline_obb("NVDA", "us", "2024-01-01")
    assert len(rows) == 3
    assert rows[0][1:] == (100.0, 102.5, 105.0, 99.0, 1000.0)


def test_obb_dedups_repeated_dates(monkeypatch):
    """重复日期索引去重（升序保序）。"""
    df = _fake_df()
    df = pd.concat([df, df.iloc[[0]]])  # 追加重复 2024-01-02
    _patch_hist(monkeypatch, _fake_res(df))
    rows = _backfill_kline_obb("NVDA", "us", "2024-01-01")
    assert len(rows) == 3


def test_obb_empty_raises(monkeypatch):
    _patch_hist(monkeypatch, _fake_res(pd.DataFrame()))
    with pytest.raises(RuntimeError, match="无数据"):
        _backfill_kline_obb("NVDA", "us", "2024-01-01")


# ---------- 降级链编排（backfill_kline） ----------

def _patch_akshare_us_fail(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("akshare 美股不可用")

    monkeypatch.setattr("akshare.stock_us_daily", boom)


def _patch_record_count(monkeypatch, module, captured):
    def recorder(rows, market, code, **kw):
        captured["rows"] = list(rows)
        return len(rows)

    def counter(code, market, **kw):
        return len(captured.get("rows", []))

    # 顶层 `from .storage import record_klines` 是引用快照（patch module 属性）；
    # 函数内 `from .storage import record_klines` 每次重取（patch storage 属性）。
    # 两条路径都要覆盖，避免测试误写真库。
    monkeypatch.setattr(module, "record_klines", recorder)
    monkeypatch.setattr("ashare_monitor.storage.record_klines", recorder)
    monkeypatch.setattr("ashare_monitor.storage.count_klines", counter)


def test_us_akshare_ok_skips_obb(monkeypatch):
    """akshare 美股可用 → OpenBB 不触发（权威源优先）。"""
    from ashare_monitor import backfill as bf

    df = pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03"],
        "open": [1.0, 2.0], "close": [2.0, 3.0],
        "high": [3.0, 4.0], "low": [0.5, 1.0], "volume": [10.0, 20.0],
    })
    monkeypatch.setattr("akshare.stock_us_daily",
                        lambda *a, **k: df)
    calls = {"obb": 0}
    monkeypatch.setattr(bf, "_backfill_kline_obb",
                        lambda *a, **k: calls.update(obb=calls["obb"] + 1) or [])
    captured: dict = {}
    _patch_record_count(monkeypatch, bf, captured)

    new, total = bf.backfill_kline("NVDA", "us")
    assert calls["obb"] == 0
    assert new == 2 and total == 2
    assert captured["rows"][0] == ("2024-01-02", 1.0, 2.0, 3.0, 0.5, 10.0)


def test_us_akshare_fail_falls_back_to_obb(monkeypatch):
    """美股：akshare 失败 → OpenBB(yfinance) 补位（不落腾讯/新浪死链）。"""
    from ashare_monitor import backfill as bf

    _patch_akshare_us_fail(monkeypatch)
    obb_rows = [("2024-01-02", 100.0, 102.5, 105.0, 99.0, 1000.0),
                ("2024-01-03", 102.0, 101.0, 104.0, 100.5, 1200.0)]
    calls = {"tencent": 0}
    monkeypatch.setattr(bf, "_backfill_kline_obb",
                        lambda code, market, start: obb_rows)
    monkeypatch.setattr(bf, "_fallback_tencent_sina",
                        lambda *a, **k: calls.update(tencent=calls["tencent"] + 1) or [])
    captured: dict = {}
    _patch_record_count(monkeypatch, bf, captured)

    new, total = bf.backfill_kline("NVDA", "us")
    assert calls["tencent"] == 0       # 美股不再走 A 股死链
    assert new == 2 and total == 2
    assert captured["rows"] == obb_rows


def test_hk_obb_first_then_tencent(monkeypatch):
    """港股：akshare 失败 → OpenBB 优先；OpenBB 也失败才腾讯 → 新浪。"""
    from ashare_monitor import backfill as bf

    def boom(*a, **k):
        raise RuntimeError("akshare 港股不可用")

    monkeypatch.setattr("akshare.stock_hk_hist", boom)
    calls = {"obb": 0, "tencent": 0}

    def obb_ok(code, market, start):
        calls["obb"] += 1
        return [("2024-01-02", 100.0, 102.5, 105.0, 99.0, 1000.0)]

    def tencent_fallback(*a, **k):
        calls["tencent"] += 1
        return [("2024-01-03", 1.0, 2.0, 3.0, 0.5, 10.0)]

    monkeypatch.setattr(bf, "_backfill_kline_obb", obb_ok)
    monkeypatch.setattr(bf, "_fallback_tencent_sina", tencent_fallback)
    captured: dict = {}
    _patch_record_count(monkeypatch, bf, captured)

    new, _ = bf.backfill_kline("01211", "hk")
    assert calls["obb"] == 1 and calls["tencent"] == 0
    assert new == 1
    assert captured["rows"][0][0] == "2024-01-02"


def test_hk_obb_fail_then_tencent_sina(monkeypatch):
    """港股：OpenBB 失败 → 腾讯 → 新浪降级链继续工作。"""
    from ashare_monitor import backfill as bf

    def boom(*a, **k):
        raise RuntimeError("akshare 港股不可用")

    monkeypatch.setattr("akshare.stock_hk_hist", boom)

    def obb_fail(code, market, start):
        raise RuntimeError("雅虎限流 YFRateLimitError")

    def tencent_fallback(code, market, start):
        return [("2024-01-03", 1.0, 2.0, 3.0, 0.5, 10.0)]

    monkeypatch.setattr(bf, "_backfill_kline_obb", obb_fail)
    monkeypatch.setattr(bf, "_fallback_tencent_sina", tencent_fallback)
    captured: dict = {}
    _patch_record_count(monkeypatch, bf, captured)

    new, _ = bf.backfill_kline("01211", "hk")
    assert new == 1
    assert captured["rows"][0][0] == "2024-01-03"   # 来自腾讯链


def test_incremental_us_falls_back_to_obb(monkeypatch):
    """增量更新：akshare 美股失败 → OpenBB 窗口补拉。"""
    from ashare_monitor import backfill as bf

    def boom(*a, **k):
        raise RuntimeError("akshare 美股不可用")

    monkeypatch.setattr("akshare.stock_us_daily", boom)
    obb_rows = [("2024-01-02", 1.0, 2.0, 3.0, 0.5, 10.0),
                ("2024-01-03", 2.0, 3.0, 4.0, 1.0, 20.0),
                ("2024-01-04", 3.0, 4.0, 5.0, 2.0, 30.0)]
    monkeypatch.setattr(bf, "_backfill_kline_obb",
                        lambda code, market, start: obb_rows)
    captured: dict = {}
    _patch_record_count(monkeypatch, bf, captured)

    # 库内已有 01-02 → 增量窗口 start 回溯 15 天，obb 三行均落入；
    # 重复日期的去重由 record_klines 的 INSERT OR IGNORE 幂等承担
    monkeypatch.setattr("ashare_monitor.storage.load_klines",
                        lambda code, market, **kw: [
                            {"date": "2024-01-02", "open": 1, "close": 2,
                             "high": 3, "low": 0.5, "volume": 10}])
    result = bf.backfill_kline_incremental([("NVDA", "us")])
    assert result["NVDA"] == (3, 3)          # 新增 3（窗口内全部），total 3
    assert [r[0] for r in captured["rows"]] == ["2024-01-02",
                                                "2024-01-03", "2024-01-04"]
