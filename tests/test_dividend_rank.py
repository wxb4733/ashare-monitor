"""股息率榜单时长单元测试。"""

import pytest


def test_rank_persistence(monkeypatch):
    import pandas as pd

    from ashare_monitor import dividend_rank

    # 3 年数据：冀中能源每年上榜，方大特钢 2 年，茅台不上榜
    fake = {
        "20201231": pd.DataFrame([
            {"代码": "000937", "名称": "冀中能源", "现金分红-股息率": 0.10},
            {"代码": "600507", "名称": "方大特钢", "现金分红-股息率": 0.12},
            {"代码": "600519", "名称": "贵州茅台", "现金分红-股息率": 0.02},
        ]),
        "20211231": pd.DataFrame([
            {"代码": "000937", "名称": "冀中能源", "现金分红-股息率": 0.11},
            {"代码": "600507", "名称": "方大特钢", "现金分红-股息率": 0.03},  # 刚好 3%
            {"代码": "600519", "名称": "贵州茅台", "现金分红-股息率": 0.021},
        ]),
        "20221231": pd.DataFrame([
            {"代码": "000937", "名称": "冀中能源", "现金分红-股息率": 0.09},
            {"代码": "600519", "名称": "贵州茅台", "现金分红-股息率": 0.025},
        ]),
    }

    def fake_fetch(date):
        df = fake.get(date)
        if df is None:
            raise RuntimeError("no data")
        return df

    monkeypatch.setattr("ashare_monitor.dividend_rank._fetch_year", fake_fetch)
    stats = dividend_rank.rank_dividend_persistence(
        years=[2020, 2021, 2022], min_yield=3.0, top_k=None)
    top = stats[0]
    assert top.code == "000937"
    assert top.name == "冀中能源"
    assert top.years_on_list == 3
    assert top.total_years == 3
    assert top.best_yield == pytest.approx(11.0)  # 0.11 → 11%
    # 茅台 2%/2.1%/2.5% 均 <3% 不上榜
    assert all(s.code != "600519" for s in stats)


def test_rank_top_k(monkeypatch):
    import pandas as pd

    from ashare_monitor import dividend_rank

    fake = {
        "20211231": pd.DataFrame([
            {"代码": "000937", "名称": "冀中能源", "现金分红-股息率": 0.05},
            {"代码": "600519", "名称": "贵州茅台", "现金分红-股息率": 0.02},
        ]),
    }

    def fake_fetch(date):
        return fake.get(date, pd.DataFrame())

    monkeypatch.setattr("ashare_monitor.dividend_rank._fetch_year", fake_fetch)
    stats = dividend_rank.rank_dividend_persistence(
        years=[2021], min_yield=99.0, top_k=1)  # 阈值 99% 无命中，但 TOP1 口径生效
    assert len(stats) == 1
    assert stats[0].code == "000937"


def test_build_rank_report():
    from ashare_monitor.dividend_rank import RankStat, build_rank_report

    stats = [
        RankStat("000937", "冀中能源", 5, 9, [2020, 2021, 2022, 2023, 2024],
                 13.59, 8.0),
        RankStat("600507", "方大特钢", 4, 9, [2017, 2018, 2020, 2021],
                 12.97, None),
    ]
    html, md = build_rank_report(stats, (2017, 2026), 3.0, None,
                                 as_of="2026-08-22")
    assert "占据股息率榜单时间最长" in html
    assert "冀中能源" in html and "5/9" in html
    assert "13.59%" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 股息率榜单时长")
