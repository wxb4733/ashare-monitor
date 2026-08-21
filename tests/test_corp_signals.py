"""公司信号监控单元测试（增减持/质押/研报/龙虎榜/北向/大宗/估值/产销）。"""

import pytest


# ---------- corp_events ----------

def test_corp_event_classify():
    from ashare_monitor.corp_events import classify_event

    assert classify_event("关于股东减持计划的公告") == ("减持", "减持计划")
    assert classify_event("关于控股股东增持股份的公告") == ("增持", "增持股份")
    assert classify_event("关于回购股份方案的公告") == ("回购", "回购股份")
    assert classify_event("2026年半年度报告") is None


def test_corp_events_save_load(tmp_path, monkeypatch):
    import ashare_monitor.storage as storage
    from ashare_monitor.corp_events import (
        CorpEvent,
        load_saved_events,
        save_corp_events,
    )

    db = str(tmp_path / "ce.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    rows = [CorpEvent("002594", "比亚迪", "2026-08-10", "减持计划公告",
                      "减持", "http://x/1", "减持计划", "")]
    assert save_corp_events(rows) == 1
    assert save_corp_events(rows) == 0  # 去重
    assert len(load_saved_events()) == 1


# ---------- pledge ----------

def test_pledge_scan(monkeypatch):
    import pandas as pd
    from ashare_monitor.pledge import scan_watchlist_pledges

    def fake(date):
        return [
            type("P", (), {
                "code": "002594", "name": "比亚迪",
                "announce_date": "2026-08-20", "pledger": "王传福",
                "pledgee": "中信证券", "pledge_shares": 5e7,
                "ratio": 0.17, "release_shares": None,
            })(),
        ]

    monkeypatch.setattr("ashare_monitor.pledge.fetch_pledges", fake)
    cfg = type("C", (), {"watchlist": [
        {"code": "002594", "market": "ashare", "name": "比亚迪"}]})()
    rows = scan_watchlist_pledges(cfg, days=3)
    assert len(rows) >= 1
    assert rows[0].pledger == "王传福"


# ---------- rating ----------

def test_rating_scan(monkeypatch):
    from ashare_monitor.rating import scan_ratings

    monkeypatch.setattr(
        "ashare_monitor.announcements.fetch_research_reports",
        lambda code, days=30, limit=10: [
            {"date": "2026-08-03", "title": "销量点评",
             "org": "东吴证券", "eps_this_year": 4.43, "pe_this_year": 17.29,
             "url": "http://x"},
        ])
    cfg = type("C", (), {"watchlist": [
        {"code": "002594", "market": "ashare", "name": "比亚迪"}]})()
    rows = scan_ratings(cfg)
    assert len(rows) == 1
    assert rows[0].org == "东吴证券"
    assert rows[0].eps_this_year == pytest.approx(4.43)


# ---------- valuation ----------

def test_valuation_fetch(monkeypatch):
    from ashare_monitor.valuation import fetch_valuation

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"result": {"data": [
                {"TRADE_DATE": "2026-08-20 00:00:00", "CLOSE_PRICE": 90.48,
                 "PE_TTM": 29.94, "PB_MRQ": 3.56},
                {"TRADE_DATE": "2026-08-19 00:00:00", "CLOSE_PRICE": 89.0,
                 "PE_TTM": 20.0, "PB_MRQ": 2.5},
                {"TRADE_DATE": "2026-08-18 00:00:00", "CLOSE_PRICE": 88.0,
                 "PE_TTM": 40.0, "PB_MRQ": 5.0},
            ]}}

    monkeypatch.setattr("ashare_monitor.valuation.requests.get",
                        lambda *a, **k: _Resp())
    v = fetch_valuation("002594", years=1, name="比亚迪")
    assert v.pe_ttm == pytest.approx(29.94)
    assert v.pe_pct == pytest.approx(66.7)  # ≤29.94 的有 2/3
    assert v.date == "2026-08-20"


# ---------- sector ----------

def test_sales_parse():
    from ashare_monitor.sector import parse_sales

    sales, unit, raw = parse_sales("2026年7月产销快报：新能源汽车销量38.16万辆")
    assert sales == pytest.approx(38.16)
    assert unit == "万辆"


def test_sales_scan(monkeypatch):
    from ashare_monitor.sector import scan_sales

    monkeypatch.setattr(
        "ashare_monitor.announcements.fetch_announcements",
        lambda code, limit=30: [
            {"date": "2026-08-03",
             "title": "2026年7月产销快报：新能源汽车销量38.16万辆"},
            {"date": "2026-08-01", "title": "2026年半年度报告"},
        ])
    cfg = type("C", (), {"watchlist": [
        {"code": "002594", "market": "ashare", "name": "比亚迪"}]})()
    rows = scan_sales(cfg)
    assert len(rows) == 1
    assert rows[0].sales == pytest.approx(38.16)
    assert rows[0].month == "2026-07"
