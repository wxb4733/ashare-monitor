"""个股资料完整性体检单元测试。"""

import pytest

from ashare_monitor.check import _miss, _ok, _warn, build_check_report


def test_check_helpers():
    assert _ok("a").status == "OK"
    assert _warn("a").status == "WARN"
    assert _miss("a").status == "MISSING"


def test_check_stock_hk_limited(monkeypatch):
    from ashare_monitor.check import check_stock

    monkeypatch.setattr("ashare_monitor.storage.load_klines",
                        lambda code, market: [{"date": "2026-08-19",
                                               "close": 100.0}] * 200)
    checks = check_stock("01211", "比亚迪股份", "hk")
    names = {c.name for c in checks}
    assert "K线历史" in names
    assert "基本面" in names  # 港股标注受限（WARN）
    hk_notes = [c for c in checks if c.name == "基本面"]
    assert hk_notes and hk_notes[0].status == "WARN"


def test_check_stock_ashare(monkeypatch):
    from ashare_monitor.check import check_stock

    monkeypatch.setattr("ashare_monitor.storage.load_klines",
                        lambda code, market: [{"date": f"2026-07-{i:02d}",
                                               "close": 100.0}
                                              for i in range(1, 30)])
    # 关键维度 mock 成功
    monkeypatch.setattr("ashare_monitor.fundamentals.fetch_financials",
                        lambda code, periods=2, market="ashare": [type("F", (), {
                            "roe": 18.5, "profit_yoy": 12.3,
                            "report_date": "2026-06-30"})()])
    monkeypatch.setattr("ashare_monitor.valuation.fetch_valuation",
                        lambda code, years=5: type("V", (), {
                            "pe_ttm": 29.9, "pe_pct": 48.0,
                            "pb_mrq": 3.56, "pb_pct": 3.0})())
    monkeypatch.setattr("ashare_monitor.holders.fetch_top10",
                        lambda code, market: ([type("H", (), {
                            "rank": 1, "name": "王传福", "ratio": 16.9})()],
                            "2026-03-31"))
    monkeypatch.setattr("ashare_monitor.holders.concentration_status",
                        lambda code: ("集中", "户数减少"))
    monkeypatch.setattr("ashare_monitor.events.fetch_events",
                        lambda code, market, days=60: [])
    monkeypatch.setattr("ashare_monitor.litigation.scan_watchlist_lawsuits",
                        lambda cfg, days=365: [])
    monkeypatch.setattr("ashare_monitor.profile.fetch_profile",
                        lambda code, market: type("P", (), {
                            "legal_person": "王传福",
                            "full_name": "比亚迪股份有限公司",
                            "reg_capital": 911719.0, "errors": []})())
    monkeypatch.setattr("ashare_monitor.arxiv.fetch_arxiv",
                        lambda query, max_results=5: [])

    cfg = type("C", (), {"watchlist": [
        {"code": "002594", "market": "ashare", "name": "比亚迪"}]})()
    checks = check_stock("002594", "比亚迪", "ashare", cfg=cfg)
    names = {c.name for c in checks}
    assert "K线历史" in names and "基本面" in names and "估值分位" in names
    assert "工商档案" in names and "研报" in names
    statuses = [c.status for c in checks]
    assert any(s == "OK" for s in statuses)


def test_build_check_report():
    checks = [_ok("K线历史", "100 根"),
              _warn("北向持股", "2024-08-16 后停每日披露"),
              _miss("产销快报", "正文提取失败")]
    html, md = build_check_report("002594", "比亚迪", checks,
                                  as_of="2026-08-21")
    assert "个股资料完整性体检" in html
    assert "OK" in html and "WARN" in html and "MISSING" in html
    assert "2024-08-16 后停每日披露" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 资料体检")
