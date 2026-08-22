"""历史股息率回填单元测试。"""

import pytest


def test_fetch_dividend_history(monkeypatch, tmp_path):
    import pandas as pd

    from ashare_monitor import dividend

    # mock 分红报表（3 年有数据，2 年无）
    fake_dfs = {
        "20201231": pd.DataFrame([{
            "股票代码": "002594", "股票简称": "比亚迪",
            "现金分红-现金分红比例": 1.0,  # 每 10 股派 1 元
        }]),
        "20211231": pd.DataFrame([{
            "股票代码": "002594", "股票简称": "比亚迪",
            "现金分红-现金分红比例": 3.0,
        }]),
        "20221231": pd.DataFrame([{
            "股票代码": "002594", "股票简称": "比亚迪",
            "现金分红-现金分红比例": 5.0,
        }, {
            "股票代码": "002594", "股票简称": "比亚迪",
            "现金分红-现金分红比例": 5.0,  # 年内两次分红
        }]),
    }

    def fake_fhps(date):
        df = fake_dfs.get(date)
        if df is None:
            return pd.DataFrame()
        return df

    monkeypatch.setattr("akshare.stock_fhps_em", fake_fhps)
    # 年末价
    def fake_year_end(code):
        return {2020: 100.0, 2021: 200.0, 2022: 300.0, 2023: 250.0,
                2024: 280.0, 2025: 300.0}

    monkeypatch.setattr("ashare_monitor.dividend._year_end_price",
                        fake_year_end)
    monkeypatch.setattr("ashare_monitor.dividend.YEARS",
                        [2020, 2021, 2022, 2023, 2024, 2025])

    rows = dividend.fetch_dividend_history("002594", "比亚迪")
    by_year = {r.year: r for r in rows}
    # 2020: dps=0.1, 价 100 → 0.1%
    assert by_year[2020].dps == pytest.approx(0.1)
    assert by_year[2020].yield_pct == pytest.approx(0.1)
    # 2022: 两次分红 dps=1.0, 价 300 → 0.333%
    assert by_year[2022].dps == pytest.approx(1.0)
    assert by_year[2022].n_payments == 2
    assert by_year[2022].yield_pct == pytest.approx(0.3333, abs=0.001)
    # 2023-2025 无分红
    assert by_year[2023].dps is None


def test_save_load(tmp_path, monkeypatch):
    from ashare_monitor import dividend
    import ashare_monitor.storage as storage

    db = str(tmp_path / "dv.db")
    orig = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))
    rows = [dividend.DividendYear("002594", "比亚迪", 2022, 1.0, 300.0,
                                  0.3333, 2)]
    assert dividend.save_dividend_history(rows) == 1
    assert dividend.save_dividend_history(rows) == 1  # REPLACE 也计 1
    loaded = dividend.load_dividend_history("002594")
    assert len(loaded) == 1
    assert loaded[0].yield_pct == pytest.approx(0.3333)


def test_fetch_sgr_history(monkeypatch):
    import pandas as pd

    from ashare_monitor import dividend

    # 3 年业绩报表：ROE + EPS
    report_2020 = {"002594": {"SECURITY_CODE": "002594",
                              "SECURITY_NAME_ABBR": "比亚迪",
                              "WEIGHTAVG_ROE": 20.0, "BASIC_EPS": 1.5}}
    report_2021 = {"002594": {"SECURITY_CODE": "002594",
                              "SECURITY_NAME_ABBR": "比亚迪",
                              "WEIGHTAVG_ROE": 30.0, "BASIC_EPS": 3.0}}

    def fake_report(rd):
        if rd == "2020-12-31":
            return report_2020
        if rd == "2021-12-31":
            return report_2021
        return {}

    monkeypatch.setattr("ashare_monitor.dividend._fetch_report_year",
                        fake_report)
    div_map = {
        "20201231": pd.DataFrame([{"代码": "002594", "名称": "比亚迪",
                                   "现金分红-现金分红比例": 10.0}]),  # 每股 1.0
        "20211231": pd.DataFrame([{"代码": "002594", "名称": "比亚迪",
                                   "现金分红-现金分红比例": 30.0}]),  # 每股 3.0
    }

    def fake_fhps(date):
        return div_map.get(date, pd.DataFrame())

    monkeypatch.setattr("akshare.stock_fhps_em",
                        fake_fhps)
    monkeypatch.setattr("ashare_monitor.dividend.datetime", __import__("datetime").datetime)
    rows = dividend.fetch_sgr_history("002594", "比亚迪")
    by = {r.year: r for r in rows}
    # 2020: 支付率 1.0/1.5=66.7% → SGR 20×(1-0.667)=6.67
    assert by[2020].sgr == pytest.approx(6.67, abs=0.05)
    # 2021: 支付率 3.0/3.0=100% → SGR 0（全分光）
    assert by[2021].sgr == pytest.approx(0.0)
    assert by[2021].payout_pct == pytest.approx(100.0)


def test_build_dividend_report():
    from ashare_monitor.dividend import DividendYear, build_dividend_report

    hist = {"002594": [
        DividendYear("002594", "比亚迪", 2020, 0.1, 100.0, 0.1, 1),
        DividendYear("002594", "比亚迪", 2022, 1.0, 300.0, 0.3333, 2),
        DividendYear("002594", "比亚迪", 2023, None, 250.0, None, 0),
    ]}
    html, md = build_dividend_report(hist, as_of="2026-08-22")
    assert "历史股息率" in html
    assert "比亚迪" in html and "0.33%" in html
    assert "最新 0.33%" in html
    assert "分红 2 年" in html  # 2020/2022 有分红，2023 空行压缩
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 历史股息率")


def test_years_since_1990():
    from ashare_monitor.dividend import YEARS

    assert YEARS[0] == 1990
    assert len(YEARS) >= 36  # A 股开市至今 36 年
    assert YEARS[-1] >= 2025
