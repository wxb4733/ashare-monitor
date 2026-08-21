"""股东分析单元测试（mock 网络）。"""

import pytest

from ashare_monitor.holders import (
    HolderNumRow,
    TopHolder,
    analyze_gdhs,
    build_holders_report,
    fetch_gdhs,
    fetch_top10,
    _latest_report_date,
)


def test_latest_report_date_from_db(tmp_path, monkeypatch):
    rows = [{"report_date": "2026-03-31"}]
    monkeypatch.setattr("ashare_monitor.storage.load_financials",
                        lambda code, db_path=None: rows)
    assert _latest_report_date("002594", "ashare") == "2026-03-31"


def test_fetch_top10(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"sdgd": [
                {"HOLDER_RANK": 1, "HOLDER_NAME": "HKSCC NOMINEES LIMITED",
                 "SHARES_TYPE": "流通H股", "HOLD_NUM": 3681473217,
                 "HOLD_NUM_RATIO": 40.38, "HOLDER_CHANGE": "增持",
                 "HOLDER_CHANGE_RATIO": 0.2},
                {"HOLDER_RANK": 2, "HOLDER_NAME": "王传福",
                 "SHARES_TYPE": "流通A股", "HOLD_NUM": 1540871550,
                 "HOLD_NUM_RATIO": 16.9, "HOLDER_CHANGE": "不变",
                 "HOLDER_CHANGE_RATIO": None},
            ]}

    monkeypatch.setattr("ashare_monitor.holders.requests.get",
                        lambda *a, **k: _Resp())
    holders, rd = fetch_top10("002594", "ashare", report_date="2026-03-31")
    assert len(holders) == 2
    assert holders[0].name == "HKSCC NOMINEES LIMITED"
    assert holders[0].ratio == pytest.approx(40.38)
    assert holders[0].hold_num == 3681473217
    assert rd == "2026-03-31"


def test_fetch_gdhs(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"result": {"data": [
                {"END_DATE": "2026-06-30 00:00:00", "HOLDER_NUM": 461893,
                 "PRE_HOLDER_NUM": 480000, "INTERVAL_CHRATE": -3.77,
                 "AVG_MARKET_CAP": 1900000.0, "AVG_HOLD_NUM": 3200.0,
                 "TOTAL_MARKET_CAP": 8.8e11},
                {"END_DATE": "2026-03-31 00:00:00", "HOLDER_NUM": 480000,
                 "PRE_HOLDER_NUM": 520000, "INTERVAL_CHRATE": -7.69,
                 "AVG_MARKET_CAP": 1750000.0, "AVG_HOLD_NUM": 3080.0,
                 "TOTAL_MARKET_CAP": 8.4e11},
            ]}}

    monkeypatch.setattr("ashare_monitor.holders.requests.get",
                        lambda *a, **k: _Resp())
    rows = fetch_gdhs("002594")
    assert len(rows) == 2
    assert rows[0].end_date == "2026-06-30"
    assert rows[0].holder_num == 461893
    assert rows[0].change_pct == pytest.approx(-3.77)


def test_analyze_gdhs_concentration():
    rows = [
        HolderNumRow("2026-06-30", 400000, 450000, -11.1, 2.0e6, 5000, 8e11),
        HolderNumRow("2026-03-31", 450000, 500000, -10.0, 1.8e6, 4400, 8.1e11),
        HolderNumRow("2025-12-31", 500000, 520000, -3.8, 1.6e6, 4000, 8e11),
        HolderNumRow("2025-06-30", 520000, 500000, 4.0, 1.5e6, 3800, 7.8e11),
    ]
    lines = analyze_gdhs(rows)
    joined = "\n".join(lines)
    assert "股东户数" in lines[0]
    assert "较半年" in joined
    assert "筹码集中" in joined  # 半年减少 >10%


def test_build_holders_report():
    holders = [
        TopHolder(1, "HKSCC NOMINEES LIMITED", "流通H股",
                  3681473217, 40.38, "增持", 0.2),
        TopHolder(2, "王传福", "流通A股", 1540871550, 16.9, "不变", None),
    ]
    rows = [
        HolderNumRow("2026-06-30", 400000, 450000, -11.1, 2.0e6, 5000, 8e11),
        HolderNumRow("2026-03-31", 450000, 500000, -10.0, 1.8e6, 4400, 8.1e11),
    ]
    html, md = build_holders_report(
        "002594", "比亚迪", "ashare", holders, rows, "2026-03-31",
        as_of="2026-08-21",
    )
    assert "股东分析" in html
    assert "HKSCC NOMINEES LIMITED" in html and "40.38%" in html
    assert "股东户数趋势" in html and "400,000" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 股东分析 比亚迪")
