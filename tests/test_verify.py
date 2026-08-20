"""信号命中率验证单元测试（合成数据）。"""

import pytest

from ashare_monitor.verify import RULES, build_verify_report, scan_signals, verify_rule


def make_rows(closes: list[float], highs: list[float] | None = None,
              lows: list[float] | None = None) -> list[dict]:
    """构造 K 线行（日期连续）。"""
    import datetime

    d = datetime.date(2024, 1, 1)
    rows = []
    for i, c in enumerate(closes):
        h = highs[i] if highs else c * 1.02
        l = lows[i] if lows else c * 0.98
        rows.append({
            "date": str(d), "open": c, "close": c, "high": h, "low": l,
            "volume": 10000.0,
        })
        d += datetime.timedelta(days=1)
    return rows


def test_scan_up_break():
    # 20 日横盘后第 21 日突破
    closes = [10.0] * 25
    closes[20] = 10.5   # 突破 20 日高 10.0
    closes[21] = 9.0    # 回落
    rows = make_rows(closes)
    idxs = scan_signals(rows, "up_break", lookback=20)
    assert 20 in idxs
    assert 21 not in idxs


def test_scan_down_break():
    closes = [10.0] * 25
    closes[20] = 9.5    # 跌破 20 日低 10.0
    rows = make_rows(closes)
    idxs = scan_signals(rows, "down_break", lookback=20)
    assert 20 in idxs


def test_scan_pct_surge_plunge():
    closes = [10.0] * 10
    # 5 日急涨 >8%
    for i in range(1, 6):
        closes.append(closes[-1] * 1.02)
    # 之后横盘
    closes += [closes[-1]] * 10
    rows = make_rows(closes)
    assert 15 in scan_signals(rows, "pct_surge", threshold=8.0)
    # 急跌
    closes2 = [10.0] * 10
    for i in range(1, 6):
        closes2.append(closes2[-1] * 0.98)
    closes2 += [closes2[-1]] * 10
    rows2 = make_rows(closes2)
    assert 14 in scan_signals(rows2, "pct_plunge", threshold=8.0)


def test_verify_rule_direction():
    # 单调上涨：上破信号后继续涨 → up 方向命中率高
    closes = [10.0 * (1.025 ** i) for i in range(120)]
    rows = make_rows(closes)
    r = verify_rule(rows, "up_break", forward=5)
    assert r["signals"] > 0
    assert 0 <= r["win_rate"] <= 100
    assert r["label"] == RULES["up_break"]["label"]
    assert r["direction"] == "up"
    # 明细字段完整
    assert r["detail"][0]["signal_date"]
    assert "forward_return_pct" in r["detail"][0]


def test_verify_rule_unknown():
    rows = make_rows([10.0] * 30)
    with pytest.raises(KeyError):
        verify_rule(rows, "no_such_rule", forward=5)


def test_build_verify_report():
    rows = make_rows([10.0 * (1.01 ** i) for i in range(60)])
    results = [verify_rule(rows, "up_break", forward=5)]
    html, md = build_verify_report("002594", "ashare", results, as_of="2026-08-20")
    assert "信号命中率验证" in html
    assert "上破20日高" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 信号命中率验证 002594")
    assert "## 规则命中率汇总" in md
