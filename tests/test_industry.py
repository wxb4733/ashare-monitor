"""乘联会行业数据单元测试。"""

import pytest


def test_parse_monthly():
    import pandas as pd

    from ashare_monitor.industry import _parse_monthly

    df = pd.DataFrame([
        {"月份": "1月", "2025年": 100.0, "2026年": 110.0},
        {"月份": "2月", "2025年": 90.0, "2026年": None},
    ])
    ms = _parse_monthly(df, "总销量")
    assert ms.data["2025-01"]["2025"] == pytest.approx(100.0)
    assert ms.data["2026-01"]["2026"] == pytest.approx(110.0)
    assert "2026-02" not in ms.data  # NaN 跳过
    latest = ms.latest()
    assert latest == ("2026-01", 110.0)


def test_fetch_industry(monkeypatch):
    import pandas as pd

    from ashare_monitor.industry import fetch_industry

    total_df = pd.DataFrame([{"月份": "8月", "2026年": 200.0}])
    fuel_df = pd.DataFrame([{"月份": "8月", "2026年": 100.0}])
    rank_df = pd.DataFrame([
        {"厂商": "比亚迪汽车", "2025年7月": 34.1, "2026年7月": 41.06},
        {"厂商": "一汽大众", "2025年7月": 20.0, "2026年7月": 18.5},
    ])
    monkeypatch.setattr("akshare.car_market_total_cpca",
                        lambda: total_df)
    monkeypatch.setattr("akshare.car_market_fuel_cpca",
                        lambda: fuel_df)
    monkeypatch.setattr("akshare.car_market_man_rank_cpca",
                        lambda: rank_df)
    ind = fetch_industry()
    # 渗透率 = 100/200 = 50%
    assert ind.penetration["2026-08"] == pytest.approx(50.0)
    assert len(ind.man_rank) == 2
    assert ind.man_rank[0]["name"] == "比亚迪汽车"
    assert ind.man_rank[0]["chg"] == pytest.approx(20.4, abs=0.1)


def test_parse_flat():
    import pandas as pd

    from ashare_monitor.industry import _parse_flat

    df = pd.DataFrame([
        {"月份": "2025-8月", "德系": 12.6, "自主": 69.6},
        {"月份": "2025-9月", "德系": 12.1, "自主": 70.3},
    ])
    rows = _parse_flat(df)
    assert rows[0]["月份"] == "2025-08"
    assert rows[0]["自主"] == pytest.approx(69.6)


def test_fetch_detail(monkeypatch):
    import pandas as pd

    from ashare_monitor.industry import IndustryData, MonthlySeries, fetch_detail

    seg_df = pd.DataFrame([{"月份": "2025-8月", "A": 35.6, "B": 31.4}])
    ctr_df = pd.DataFrame([{"月份": "2025-8月", "自主": 69.6, "德系": 12.6}])
    li_df = pd.DataFrame([
        {"date": "2026-06-01", "close": 100000.0},
        {"date": "2026-08-21", "close": 152160.0},
    ])
    monkeypatch.setattr("akshare.car_market_segment_cpca",
                        lambda: seg_df)
    monkeypatch.setattr("akshare.car_market_country_cpca",
                        lambda: ctr_df)
    monkeypatch.setattr("akshare.futures_zh_daily_sina",
                        lambda symbol: li_df)
    ind = fetch_detail(IndustryData(MonthlySeries("总销量"), MonthlySeries("新能源")))
    assert ind.segment[0]["A"] == pytest.approx(35.6)
    assert ind.country[0]["自主"] == pytest.approx(69.6)
    assert ind.lithium[-1]["close"] == pytest.approx(152160.0)


def test_build_industry_report():
    from ashare_monitor.industry import (
        IndustryData,
        MonthlySeries,
        build_industry_report,
    )

    ind = IndustryData(
        total=MonthlySeries("总销量", {"2026-08": {"2026": 200.0}}),
        new_energy=MonthlySeries("新能源", {"2026-08": {"2026": 100.0}}),
        penetration={"2026-08": 50.0},
        man_rank=[{"rank": 1, "name": "比亚迪汽车", "cur": 41.06,
                   "prev": 34.1, "chg": 20.4}],
    )
    html, md = build_industry_report(ind, as_of="2026-08-21")
    assert "汽车行业景气数据" in html
    assert "200.0" in html and "50.0%" in html
    assert "比亚迪汽车" in html and "+20.4%" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 汽车行业数据")
