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
