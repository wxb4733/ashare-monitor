# -*- coding: utf-8 -*-
"""scripts/backfill_kline_all.py universe 组装测试（不触库、不联网）。

回归背景（2026-11-03）：11-01 调仓买入的 10 只高股息股在 klines 表零行，
universe 只从 klines 反查 → 它们永远进不了回填范围（无法离线估值/补录/复盘）。
"""
from scripts.backfill_kline_all import infer_market, merge_universe

MARKETS = ("ashare", "hk")


def test_infer_market_by_code_shape():
    assert infer_market("600519") == "ashare"
    assert infer_market("000915") == "ashare"
    assert infer_market("01211") == "hk"
    assert infer_market(" 00700 ") == "hk"


def test_positions_without_klines_enter_universe():
    """持仓中零 K 线的标的必须进 universe，且排在前面优先补。"""
    got = merge_universe([("ashare", "600519")], ["000915", "002572"], MARKETS)
    assert got == [("ashare", "000915"), ("ashare", "002572"), ("ashare", "600519")]


def test_merge_dedupes_position_already_in_klines():
    got = merge_universe([("ashare", "600519"), ("ashare", "000915")],
                         ["000915"], MARKETS)
    assert got == [("ashare", "000915"), ("ashare", "600519")]


def test_merge_respects_markets_filter():
    """--market ashare 时不应把港股持仓带进来。"""
    got = merge_universe([("ashare", "600519")], ["01211"], ("ashare",))
    assert got == [("ashare", "600519")]


def test_kline_rows_from_other_markets_filtered():
    got = merge_universe([("ashare", "600519"), ("crypto", "BTCUSDT")],
                         [], MARKETS)
    assert got == [("ashare", "600519")]
