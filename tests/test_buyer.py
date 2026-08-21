"""买方视角单元测试（预测修正/基金重仓/风险收益）。"""

import pytest


def test_prediction_upside(monkeypatch):
    from ashare_monitor.buyer import fetch_prediction

    monkeypatch.setattr(
        "ashare_monitor.announcements.fetch_research_reports",
        lambda code, days=120, limit=50: [
            {"date": "2026-08-03", "org": "华金", "eps_this_year": 4.51},
            {"date": "2026-04-30", "org": "开源", "eps_this_year": 4.30},
            {"date": "2026-04-29", "org": "东吴", "eps_this_year": 4.20},
            {"date": "2026-04-29", "org": "国金", "eps_this_year": 4.10},
        ])
    p = fetch_prediction("002594", "比亚迪")
    assert p.direction == "上修"
    assert p.latest_eps == pytest.approx(4.51)
    assert p.chg_pct > 0


def test_prediction_missing(monkeypatch):
    from ashare_monitor.buyer import fetch_prediction

    monkeypatch.setattr("ashare_monitor.announcements.fetch_research_reports",
                        lambda code, days=120, limit=50: [])
    p = fetch_prediction("002594", "比亚迪")
    assert p.direction == "数据缺失"


def test_fund_holds(monkeypatch):
    import pandas as pd

    from ashare_monitor.buyer import fetch_fund_holds

    df = pd.DataFrame([
        {"股票代码": "002594", "股票简称": "比亚迪", "持有基金家数": 142,
         "持股总数": 75681121, "持股市值": 6.03e9,
         "持股变化": "减仓", "持股变动数值": -49741756,
         "持股变动比例": -39.66},
    ])
    monkeypatch.setattr("akshare.stock_report_fund_hold",
                        lambda symbol, date: df)
    cfg = type("C", (), {"watchlist": [
        {"code": "002594", "market": "ashare", "name": "比亚迪"}]})()
    hits = fetch_fund_holds(cfg)
    assert len(hits) == 1
    assert hits[0].fund_count == 142
    assert hits[0].change == "减仓"
    assert hits[0].change_ratio == pytest.approx(-39.66)


def test_risk_metrics(monkeypatch):
    from ashare_monitor.buyer import RiskMetric, risk_metrics

    rows = [{"date": f"2026-01-{i:02d}", "close": 100 + i}
            for i in range(60)]
    monkeypatch.setattr("ashare_monitor.storage.load_klines",
                        lambda code, market: rows)
    r = risk_metrics("002594", "比亚迪", "ashare")
    assert r.annual_vol is not None and r.annual_vol > 0
    assert r.max_drawdown is not None and r.max_drawdown >= 0
    assert r.sharpe is not None


def test_correlation():
    from ashare_monitor.buyer import _corr

    a = [1, 2, 3, 4, 5]
    b = [2, 4, 6, 8, 10]
    c = [5, 4, 3, 2, 1]
    assert _corr(a, b) == pytest.approx(1.0)
    assert _corr(a, c) == pytest.approx(-1.0)


def test_build_buyer_report():
    from ashare_monitor.buyer import (
        FundHold,
        Prediction,
        RiskMetric,
        build_buyer_report,
    )

    preds = [Prediction("002594", "比亚迪", 4.51, 4.45, "上修", 1.3)]
    holds = [FundHold("002594", "比亚迪", "2026-06-30", 142, 75681121,
                      6.03e9, "减仓", -39.66)]
    risks = [RiskMetric("002594", "比亚迪", 32.5, 18.2, 0.85, 250)]
    html, md = build_buyer_report(preds, holds, risks, ["比亚迪"], [[1.0]],
                                  as_of="2026-08-21")
    assert "买方基金经理视角" in html
    assert "上修" in html and "减仓" in html
    assert "32.5%" in html and "0.85" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 买方视角")
