"""个股体检单元测试（合成数据 + mock 网络）。"""

import pytest

from ashare_monitor.doctor import (
    Dimension,
    _chip,
    _event,
    _fundamental,
    _fundflow,
    _technical,
    build_doctor_report,
    run_doctor,
)


def _rows(n=80, base=10.0, trend=0.02):
    rows = []
    c = base
    for i in range(n):
        c = c * (1 + trend)
        rows.append({"date": f"2025-01-{i % 28 + 1:02d}", "open": c,
                     "close": c, "high": c * 1.02, "low": c * 0.98,
                     "volume": 10000.0})
    return rows


def test_technical_score():
    # 上涨趋势 → 技术分高
    d = _technical(_rows(trend=0.02), 60.0)
    assert d.key == "technical"
    assert d.score is not None and d.score >= 60
    assert "MA20" in d.detail


def test_fundamental_score(monkeypatch):
    class P:
        report_date = "2026-03-31"
        roe = 18.0
        profit_yoy = 25.0
        revenue_yoy = 10.0
        gross_margin = 25.0

    monkeypatch.setattr("ashare_monitor.fundamentals.fetch_financials",
                        lambda code, periods=2: [P()])
    d = _fundamental("002594")
    assert d.score == 90  # ROE>=15(60) + 净利>0(20) + >20%(10) + 毛利25%<30(0)
    assert "ROE 18.0%" in d.detail


def test_fundamental_missing(monkeypatch):
    monkeypatch.setattr("ashare_monitor.fundamentals.fetch_financials",
                        lambda code, periods=2: [])
    d = _fundamental("002594")
    assert d.score is None


def test_chip_score(monkeypatch):
    monkeypatch.setattr("ashare_monitor.holders.concentration_status",
                        lambda code: ("集中", "户数减少 20%"))
    assert _chip("002594").score == 100
    monkeypatch.setattr("ashare_monitor.holders.concentration_status",
                        lambda code: ("分散", "户数增加 15%"))
    assert _chip("002594").score == 35


def test_fundflow_score(monkeypatch):
    class F:
        main_net = 2.5
        date = "2026-08-20"

    monkeypatch.setattr("ashare_monitor.fundflow.fetch_fundflow",
                        lambda *a, **k: F())
    assert _fundflow("002594").score == 90


def test_event_score(monkeypatch):
    from ashare_monitor.events import CalendarEvent

    monkeypatch.setattr("ashare_monitor.events.fetch_events",
                        lambda code, market, days=30: [
                            CalendarEvent("002594", "比亚迪", "ashare", "解禁",
                                          "2026-09-01", "解禁市值 5 亿"),
                        ])
    assert _event("002594").score == 35  # 解禁 → 最低 35


def test_run_doctor(monkeypatch):
    # mock 掉网络维度，只用 K 线
    monkeypatch.setattr("ashare_monitor.storage.load_klines",
                        lambda code, market, db_path=None: _rows())
    monkeypatch.setattr("ashare_monitor.quotes.fetch_spot_quotes",
                        lambda codes, sources=None: [])
    monkeypatch.setattr("ashare_monitor.fundamentals.fetch_financials",
                        lambda code, periods=2: [])
    monkeypatch.setattr("ashare_monitor.holders.concentration_status",
                        lambda code: (None, ""))
    monkeypatch.setattr("ashare_monitor.fundflow.fetch_fundflow",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr("ashare_monitor.events.fetch_events",
                        lambda code, market, days=30: [])

    data = run_doctor("002594", "ashare", "比亚迪")
    assert data["code"] == "002594"
    assert data["total"] is not None and 0 <= data["total"] <= 100
    assert data["verdict"] in ("强势", "中性", "谨慎")
    assert any(d["key"] == "technical" for d in data["dims"])
    # 资金维度失败 → 数据缺失不计分
    ff = [d for d in data["dims"] if d["key"] == "fundflow"][0]
    assert ff["score"] is None


def test_build_doctor_report():
    data = {
        "code": "002594", "name": "比亚迪", "market": "ashare",
        "as_of": "2026-08-21", "price": 89.97, "change_pct": -0.97,
        "dims": [
            Dimension("quote", "行情", None, "现价 89.97").to_dict(),
            Dimension("technical", "技术面", 80, "MA20 88.5").to_dict(),
            Dimension("fundamental", "基本面", 90, "ROE 18%").to_dict(),
        ],
        "total": 85, "verdict": "强势",
        "timing_notes": ["MACD金叉（历史命中率 51%）"],
        "highlights": ["技术面(80分)"], "risks": [],
    }
    html, md = build_doctor_report(data)
    assert "个股全方位体检" in html
    assert "85" in html and "强势" in html
    assert "MACD金叉" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 个股体检 比亚迪")
