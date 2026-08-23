"""信号雷达与一键日报单元测试。"""

import pytest


def test_radar_verdict():
    from ashare_monitor.radar import _verdict, StockRadar, RadarSignal

    assert _verdict(2.5) == "偏多"
    assert _verdict(-2.5) == "偏空"
    assert _verdict(0.5) == "中性"


def test_radar_score_stock(monkeypatch):
    from ashare_monitor.radar import score_stock

    # 全维度 mock 确定性信号
    monkeypatch.setattr("ashare_monitor.storage.load_klines",
                        lambda code, market, db_path=None: [])
    monkeypatch.setattr("ashare_monitor.timing.scan_timing",
                        lambda rows, code, name, market: [type("S", (), {
                            "label": "MACD金叉"})()])
    monkeypatch.setattr("ashare_monitor.holders.concentration_status",
                        lambda code: ("集中", "户数减少 20%"))
    monkeypatch.setattr("ashare_monitor.fundflow.fetch_fundflow",
                        lambda *a, **k: type("F", (), {"main_net": 2.5})())
    monkeypatch.setattr("ashare_monitor.valuation.fetch_valuation",
                        lambda code, years=5: type("V", (), {
                            "pe_pct": 10.0, "pb_pct": 15.0})())
    monkeypatch.setattr("ashare_monitor.events.fetch_events",
                        lambda code, market, days=30: [])
    monkeypatch.setattr("ashare_monitor.announcements.fetch_announcements",
                        lambda code, limit=30: [
                            {"title": "关于股东减持计划的公告"}] * 0 + [])
    monkeypatch.setattr("ashare_monitor.announcements.fetch_research_reports",
                        lambda code, days=30, limit=5: [
                            {"org": "东吴", "eps_this_year": 4.0}] * 2)

    cfg = type("C", (), {"watchlist": []})()
    r = score_stock("002594", "比亚迪", "ashare", cfg=cfg)
    # 技术+1 筹码+1 资金+1 估值+1(双低估) 事件0 增减持0 质押0 研报+1 产销0
    assert r.total == pytest.approx(5.0)
    assert r.verdict == "偏多"
    assert not r.missing or set(r.missing) == {"产销"}


def test_radar_build_report():
    from ashare_monitor.radar import (
        RadarSignal,
        StockRadar,
        build_radar_report,
    )

    r = StockRadar(
        code="002594", name="比亚迪", market="ashare",
        total=3.0, verdict="偏多",
        signals=[RadarSignal("technical", "技术面", 1.0, "MACD金叉")],
    )
    html, md = build_radar_report([r], as_of="2026-08-21")
    assert "信号聚合雷达" in html
    assert "+3.0" in html and "偏多" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 信号聚合雷达")


def test_daily_freshness():
    from datetime import datetime, timedelta

    from ashare_monitor.daily import _freshness

    today = datetime.now().strftime("%Y-%m-%d")
    stale = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    ok, note = _freshness([{"date": today}])
    assert ok and "正常" in note
    bad, note2 = _freshness([{"date": stale}])
    assert not bad and "落后" in note2
    bad2, _ = _freshness([])
    assert not bad2


def test_daily_build_report():
    from ashare_monitor.daily import build_daily_report

    data = {
        "items": [{
            "code": "002594", "name": "比亚迪", "market": "ashare",
            "quote": {"price": 90.48, "change_pct": 1.2, "date": "2026-08-20"},
            "radar": None, "timing": ["MACD金叉"], "events": ["分红除权 2026-09-01"],
            "valuation": "PE 48% / PB 15%", "ratings": 2, "corp": ["回购:2026-08-10"],
        }],
        "health": ["比亚迪 K线: 2026-08-20（正常）"],
    }
    html, md = build_daily_report(data, as_of="2026-08-21")
    assert "每日信号日报" in html
    assert "比亚迪" in html and "90.48" in html
    assert "MACD金叉" in html and "PE 48%" in html
    assert "数据健康" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 每日信号日报")
