"""事件日历单元测试（mock 东财报表）。"""

import pytest

from ashare_monitor.events import CalendarEvent, build_events_report, fetch_events, scan_events


class _Cfg:
    def __init__(self):
        self.watchlist = [
            {"code": "002594", "market": "ashare", "name": "比亚迪"},
            {"code": "01211", "market": "hk", "name": "比亚迪股份"},
        ]


def _mock_query(monkeypatch, rows_by_report):
    def fake(report_name, filter_s, sort_col, page_size=20):
        return rows_by_report.get(report_name, [])
    monkeypatch.setattr("ashare_monitor.events._query", fake)


def test_fetch_events_dividend(monkeypatch):
    from datetime import datetime, timedelta

    future = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
    _mock_query(monkeypatch, {
        "RPT_SHAREBONUS_DET": [{
            "SECURITY_CODE": "002594", "SECURITY_NAME_ABBR": "比亚迪",
            "REPORT_DATE": "2025-12-31 00:00:00",
            "EX_DIVIDEND_DATE": f"{future} 00:00:00",
            "BONUS_RATIO": 8, "IT_RATIO": 12,
        }],
    })
    evs = fetch_events("002594", "ashare", days=30)
    kinds = [e.kind for e in evs]
    assert "分红除权" in kinds
    d = [e for e in evs if e.kind == "分红除权"][0]
    assert d.date == future
    assert "10 派 8" in d.detail and "10 转 12" in d.detail


def test_fetch_events_unlock(monkeypatch):
    from datetime import datetime, timedelta

    future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    _mock_query(monkeypatch, {
        "RPT_LIFT_STAGE": [{
            "SECURITY_CODE": "002594", "SECURITY_NAME_ABBR": "比亚迪",
            "FREE_DATE": f"{future} 00:00:00",
            "FREE_SHARES_TYPE": "首发原股东限售股份",
            "LIFT_MARKET_CAP": 50000.0, "FREE_RATIO": 1.5,   # 万元 → 5 亿
        }],
    })
    evs = fetch_events("002594", "ashare", days=30)
    u = [e for e in evs if e.kind == "解禁"][0]
    assert u.date == future
    assert "5.0 亿" in u.detail and "1.5%" in u.detail


def test_fetch_events_hk_empty(monkeypatch):
    _mock_query(monkeypatch, {})
    assert fetch_events("01211", "hk", days=30) == []


def test_scan_events_skips_crypto(monkeypatch):
    cfg = _Cfg()
    cfg.watchlist.append({"code": "BTCUSDT", "market": "crypto", "name": "BTC"})
    _mock_query(monkeypatch, {})
    assert scan_events(cfg, days=10) == []


def test_build_events_report():
    from datetime import datetime, timedelta

    d = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    evs = [
        CalendarEvent("002594", "比亚迪", "ashare", "解禁", d, "解禁市值约 5.0 亿"),
        CalendarEvent("002594", "比亚迪", "ashare", "分红除权", d, "10 派 8"),
    ]
    html, md = build_events_report(evs, days=30, as_of="2026-08-21")
    assert "事件日历提醒" in html
    assert "解禁" in html and "分红除权" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 事件日历")
