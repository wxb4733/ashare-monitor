"""backfill_queue_kline 脚本核心逻辑测试（跳过/拉取/失败降级）。"""
import pytest

import scripts.backfill_queue_kline as qk


def _rows(n: int = 5) -> list[tuple]:
    return [("2026-08-%02d" % d, 1.0, 2.0, 2.5, 0.5, 100) for d in range(1, n + 1)]


def test_run_one_skips_existing():
    """已有 K 线 → 跳过，不触发拉取。"""
    counter = lambda code, market: 123  # noqa: E731
    calls = {"fetch": 0}

    def fetcher(*a, **k):
        calls["fetch"] += 1
        return _rows()

    msg = qk.run_one("600066", "宇通客车", "1990-01-01",
                     fetcher=fetcher, recorder=lambda *a, **k: 0,
                     counter=counter)
    assert "已有 123 根，跳过" in msg
    assert calls["fetch"] == 0


def test_run_one_fetches_and_records():
    """无 K 线 → 腾讯拉取 + 落库。"""
    seen = {"recorded": []}

    def counter(code, market):
        return len(seen["recorded"])

    def recorder(rows, market, code):
        seen["recorded"] = rows
        return len(rows)

    msg = qk.run_one("000651", "格力电器", "1990-01-01",
                     fetcher=lambda *a, **k: _rows(),
                     recorder=recorder, counter=counter)
    assert "+5 根" in msg
    assert "(共 5)" in msg
    assert len(seen["recorded"]) == 5


def test_run_one_failure_propagates():
    """拉取失败 → 异常上抛（由 main 记录失败清单，不中断循环）。"""
    def fetcher(*a, **k):
        raise RuntimeError("腾讯接口超时")

    with pytest.raises(RuntimeError, match="腾讯接口超时"):
        qk.run_one("601166", "兴业银行", "1990-01-01",
                   fetcher=fetcher, recorder=lambda *a, **k: 0,
                   counter=lambda c, m: 0)
