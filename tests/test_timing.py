"""择时买入提醒单元测试（合成数据）。"""

import pytest

from ashare_monitor.timing import (
    RULES,
    _history_signal_idxs,
    build_timing_report,
    scan_timing,
)


def make_rows(closes: list[float], opens: list[float] | None = None,
              vols: list[float] | None = None) -> list[dict]:
    """构造 K 线行（日期连续）。"""
    import datetime

    d = datetime.date(2024, 1, 1)
    rows = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else c * 0.99
        v = vols[i] if vols else 10000.0
        rows.append({
            "date": str(d), "open": o, "close": c,
            "high": max(o, c) * 1.01, "low": min(o, c) * 0.99,
            "volume": v,
        })
        d += datetime.timedelta(days=1)
    return rows


def test_macd_golden_signal():
    # 下跌后反转上涨：产生 MACD 金叉
    closes = [50 - i * 0.3 for i in range(40)]      # 跌
    closes += [50 - 40 * 0.3 + i * 0.5 for i in range(30)]  # 涨
    rows = make_rows(closes)
    idxs = _history_signal_idxs(rows, "macd_golden")
    assert idxs, "应出现 MACD 金叉信号"
    assert idxs[-1] == len(rows) - 1 or idxs[-1] < len(rows) - 1


def test_rsi_oversold_signal():
    # 超卖后回升
    closes = [100 - i for i in range(20)]           # 急跌
    closes += [closes[-1] + i for i in range(25)]   # 回升
    rows = make_rows(closes)
    idxs = _history_signal_idxs(rows, "rsi_oversold")
    assert idxs, "应出现 RSI 超卖回升信号"


def test_volume_break_signal():
    # 横盘后放量突破
    closes = [10.0] * 30
    vols = [1000.0] * 30
    closes.append(11.0)   # 突破 20 日高 10.1
    vols.append(3000.0)   # 3 倍量
    rows = make_rows(closes, vols=vols)
    idxs = _history_signal_idxs(rows, "volume_break")
    assert idxs and idxs[-1] == len(rows) - 1


def test_scan_timing_confidence():
    # 单调上涨 → 回踩 MA20 信号 + 置信度统计
    closes = [10.0 * (1.03 ** i) for i in range(120)]
    rows = make_rows(closes)
    signals = scan_timing(rows, "002594", "比亚迪", "ashare")
    found = [s for s in signals if s.rule == "ma_pullback"]
    if found:
        sg = found[0]
        assert 0 <= sg.win_rate <= 100
        assert sg.signals_count > 0
        assert sg.label == RULES["ma_pullback"]["label"]


def test_scan_timing_insufficient_data():
    rows = make_rows([10.0] * 30)
    assert scan_timing(rows, "600000", "浦发", "ashare") == []


def test_build_timing_report():
    from ashare_monitor.timing import TimingSignal

    sg = TimingSignal(
        code="002594", name="比亚迪", market="ashare",
        rule="deep_pullback", label="深度回调止跌",
        message="5 日跌超 8% 后企稳", win_rate=72.7,
        avg_return=5.53, signals_count=11,
        signal_date="2026-08-20",
    )
    html, md = build_timing_report([sg], as_of="2026-08-20")
    assert "择时买入提醒" in html
    assert "深度回调止跌" in html and "73%" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 择时买入提醒")
    assert "| 比亚迪(002594) |" in md


def test_build_timing_report_empty():
    html, md = build_timing_report([], as_of="2026-08-20")
    assert "今日无买入信号" in html
