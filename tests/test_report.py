"""周期报告（日报/周报/月报）单元测试。"""

import pytest


def test_period_days():
    from ashare_monitor.report import _period_days

    assert _period_days("daily") == 1
    assert _period_days("weekly") == 7
    assert _period_days("monthly") == 30


def test_build_report_data(monkeypatch):
    from ashare_monitor.report import build_report_data

    # mock daily 数据 + 多视角
    monkeypatch.setattr(
        "ashare_monitor.daily.build_daily_data",
        lambda cfg, codes=None: {
            "items": [{
                "code": "002594", "name": "比亚迪", "market": "ashare",
                "quote": {"price": 90.0, "change_pct": 1.2, "date": "2026-08-20"},
                "radar": None, "timing": [], "events": [],
                "valuation": None, "ratings": 2, "corp": [],
            }],
            "health": ["比亚迪 K线: 2026-08-20（正常）"],
        })
    monkeypatch.setattr("ashare_monitor.buyer.fetch_prediction",
                        lambda code, name="", days=120: type("P", (), {
                            "direction": "上修", "chg_pct": 3.5})())
    monkeypatch.setattr("ashare_monitor.buyer.fetch_fund_holds",
                        lambda cfg, codes=None: [type("F", (), {
                            "change": "减仓", "change_ratio": -39.7,
                            "fund_count": 142})()])
    monkeypatch.setattr("ashare_monitor.insider_view.analyze_insider",
                        lambda code, name, market, cfg=None: type("V", (), {
                            "total": 0.5, "verdict": "观望",
                            "gates": []})())

    cfg = type("C", (), {"watchlist": [
        {"code": "002594", "market": "ashare", "name": "比亚迪"}]})()
    data = build_report_data(cfg, period="daily")
    item = data["items"][0]
    assert item["prediction"] == "上修 +3.5%"
    assert item["fund_hold"] == "减仓 -39.7%（142 家）"
    assert item["insider"] == "+0.5 观望"
    assert data["period"] == "daily"


def test_build_period_report():
    from ashare_monitor.report import build_period_report

    data = {
        "period": "weekly", "days": 7,
        "items": [{
            "code": "002594", "name": "比亚迪", "market": "ashare",
            "quote": {"price": 90.0, "change_pct": 1.2, "date": "2026-08-20"},
            "radar": None, "timing": [], "events": ["分红除权 2026-09-01"],
            "valuation": None, "ratings": 2, "corp": [],
            "prediction": "上修 +3.5%", "fund_hold": "减仓 -39.7%",
            "insider": "+0.5 观望",
            "industry": {"penetration": "42.8%(2026-07)", "byd_rank": "第1名 41.1万"},
        }],
        "health": ["比亚迪 K线: 2026-08-20（正常）"],
    }
    html, md = build_period_report(data, as_of="2026-08-21")
    assert "投资周报（多视角）" in html
    assert "上修 +3.5%" in html and "减仓 -39.7%" in html
    assert "第1名 41.1万" in html
    assert "分红除权" in html and "数据健康" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 周报")
