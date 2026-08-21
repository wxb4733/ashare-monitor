"""大股东视角单元测试。"""

import pytest


def test_verdict():
    from ashare_monitor.insider_view import _verdict

    assert _verdict(2.5) == "增持"
    assert _verdict(-2.5) == "减持"
    assert _verdict(0.5) == "观望"


def test_analyze_insider(monkeypatch):
    from ashare_monitor.insider_view import analyze_insider

    class _V:
        pb_mrq = 0.8      # 破净 → 受限
        pb_pct = 15.0     # 低估 → 增持倾向
        close = 80.0
        pe_pct = 30.0

    class _E:
        kind = "财报披露"
        date = "2026-08-30"   # 9 天后 → 敏感期

    monkeypatch.setattr("ashare_monitor.valuation.fetch_valuation",
                        lambda code, years=5: _V())
    monkeypatch.setattr("ashare_monitor.events.fetch_events",
                        lambda code, market, days=40: [_E()])
    monkeypatch.setattr("ashare_monitor.insider_view._fetch_issue_price",
                        lambda code: None)  # 发行价受限
    monkeypatch.setattr("ashare_monitor.pledge.fetch_pledges",
                        lambda date: [])
    monkeypatch.setattr("ashare_monitor.announcements.fetch_announcements",
                        lambda code, limit=30: [])

    view = analyze_insider("002594", "比亚迪", "ashare", cfg=None)
    # 闸门：破净受限 + 敏感期受限 + 破发缺失
    assert any(g.passed is False for g in view.gates)
    assert any(g.passed is None for g in view.gates)
    # 信号：估值 +1（低估）
    val_sig = next(s for s in view.signals if s[0] == "估值")
    assert val_sig[1] == pytest.approx(1.0)
    assert view.issues  # 有受限提示


def test_build_insider_report():
    from ashare_monitor.insider_view import (
        Gate,
        InsiderView,
        build_insider_report,
    )

    view = InsiderView(
        code="002594", name="比亚迪", market="ashare",
        gates=[Gate("破净检查", False, "PB 0.80 < 1"),
               Gate("财报敏感期", True, "无近期披露")],
        signals=[("估值", 1.0, "低估"), ("基金", -0.5, "减仓")],
        total=0.5, verdict="观望",
        issues=["破净检查受限：PB 0.80 < 1"],
    )
    html, md = build_insider_report([view], as_of="2026-08-21")
    assert "大股东视角" in html
    assert "破净检查" in html and "观望" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 大股东视角")
