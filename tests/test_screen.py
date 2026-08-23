"""A 股市场扫描选股器单元测试（高股息率）。"""

import pytest

from ashare_monitor.screen import ScreenHit, build_screen_report, fetch_dividend_top


def _mock_payload():
    return {"data": {"diff": [
        {"f12": "600900", "f14": "长江电力", "f2": 28.5, "f9": 18.2,
         "f23": 3.1, "f133": 3.85, "f20": 6.97e11},
        {"f12": "601088", "f14": "中国神华", "f2": 38.9, "f9": 12.5,
         "f23": 1.8, "f133": 5.21, "f20": 7.73e11},
        {"f12": "000001", "f14": "ST平安", "f2": 10.5, "f9": 5.0,
         "f23": 0.6, "f133": 4.5, "f20": 2.0e11},
        {"f12": "600519", "f14": "贵州茅台", "f2": 1450.0, "f9": 22.0,
         "f23": 7.0, "f133": 2.1, "f20": 1.8e12},  # 股息率不足 3 被过滤
    ]}}


def test_fetch_dividend_top(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return _mock_payload()

    monkeypatch.setattr("requests.get",
                        lambda *a, **k: _Resp())
    hits = fetch_dividend_top(top_n=10, min_yield=3.0, exclude_st=True)
    # 神华 5.21 > 平安(ST 剔除) > 长电 3.85；茅台 2.1 被过滤
    assert len(hits) == 2
    assert hits[0].name == "中国神华"
    assert hits[0].dividend_yield == pytest.approx(5.21)
    assert hits[1].name == "长江电力"
    assert all("ST" not in h.name.upper() for h in hits)


def test_fetch_dividend_mv_filter(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return _mock_payload()

    monkeypatch.setattr("requests.get",
                        lambda *a, **k: _Resp())
    hits = fetch_dividend_top(top_n=10, min_yield=3.0, exclude_st=True,
                              min_mv=500)  # 500 亿以上
    assert len(hits) == 2  # 神华/长电均 > 500 亿
    hits2 = fetch_dividend_top(top_n=10, min_yield=3.0, exclude_st=True,
                               max_mv=500)
    assert len(hits2) == 0  # 无 < 500 亿的高股息（ST 已剔除）


def test_screen_raises_when_source_down(monkeypatch):
    monkeypatch.setattr("requests.get",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("connect fail")))
    monkeypatch.setattr("akshare.stock_zh_a_spot_em",
                        lambda: (_ for _ in ()).throw(
                            RuntimeError("akshare fail")))
    from ashare_monitor.screen import screen_dividend

    with pytest.raises(RuntimeError):
        screen_dividend()


def test_screen_sgr(monkeypatch):
    import pandas as pd

    from ashare_monitor.screen import screen_sgr

    report = {
        "600502": {"SECURITY_CODE": "600502", "SECURITY_NAME_ABBR": "新易盛",
                   "WEIGHTAVG_ROE": 72.8, "BASIC_EPS": 2.5},
        "002052": {"SECURITY_CODE": "002052", "SECURITY_NAME_ABBR": "同洲电子",
                   "WEIGHTAVG_ROE": 99.8, "BASIC_EPS": 0.1},
        "430282": {"SECURITY_CODE": "430282", "SECURITY_NAME_ABBR": "土友生物",
                   "WEIGHTAVG_ROE": 348.1, "BASIC_EPS": 1.0},  # 北交所排除
        "600519": {"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                   "WEIGHTAVG_ROE": 33.0, "BASIC_EPS": 60.0},
    }
    monkeypatch.setattr("ashare_monitor.screen._fetch_report_all",
                        lambda d: report)
    div_df = pd.DataFrame([
        {"代码": "600502", "名称": "新易盛", "现金分红-现金分红比例": 5.0},  # 每股 0.5
        {"代码": "600519", "名称": "贵州茅台", "现金分红-现金分红比例": 300.0},  # 每股 30
    ])
    monkeypatch.setattr("akshare.stock_fhps_em",
                        lambda date: div_df)
    hits = screen_sgr(top_n=10, min_sgr=10.0, min_roe=8.0)
    codes = {h.code for h in hits}
    assert "430282" not in codes          # 北交所排除
    # 新易盛：ROE 72.8，支付率 0.5/2.5=20% → SGR 58.2
    xe = next(h for h in hits if h.code == "600502")
    assert xe._sgr == pytest.approx(58.24, abs=0.1)
    # 茅台：支付率 30/60=50% → SGR 16.5 < 阈值 10 → 入选（>10）
    assert "600519" in codes
    # 同洲电子 ROE 99.8 <100 保留（数据源如实）
    assert "002052" in codes


def test_screen_margin(monkeypatch):
    from ashare_monitor.screen import screen_margin

    report = {
        "688111": {"SECURITY_CODE": "688111", "SECURITY_NAME_ABBR": "金山办公",
                   "TOTAL_OPERATE_INCOME": 33e8, "PARENT_NETPROFIT": 25.2e8,
                   "XSMLL": 84.9},
        "600519": {"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                   "TOTAL_OPERATE_INCOME": 1741e8, "PARENT_NETPROFIT": 862e8,
                   "XSMLL": 91.8},
        "600519X": {"SECURITY_CODE": "600519X", "SECURITY_NAME_ABBR": "ST测试",
                    "TOTAL_OPERATE_INCOME": 10e8, "PARENT_NETPROFIT": 5e8,
                    "XSMLL": 50.0},
        "000001": {"SECURITY_CODE": "000001", "SECURITY_NAME_ABBR": "平安银行",
                   "TOTAL_OPERATE_INCOME": 5000e8, "PARENT_NETPROFIT": 300e8,
                   "XSMLL": 30.0},   # 净利率 6% < 20 过滤
        "430282": {"SECURITY_CODE": "430282", "SECURITY_NAME_ABBR": "土友生物",
                   "TOTAL_OPERATE_INCOME": 1e8, "PARENT_NETPROFIT": 0.9e8,
                   "XSMLL": 90.0},   # 北交所排除
    }
    monkeypatch.setattr("ashare_monitor.screen._fetch_report_all",
                        lambda d: report)
    hits = screen_margin(top_n=10, min_margin=20.0, min_rev=1.0)
    codes = {h.code for h in hits}
    assert "688111" in codes and "600519" in codes
    assert "000001" not in codes          # 净利率低
    assert "600519X" not in codes         # ST 剔除
    assert "430282" not in codes          # 北交所剔除
    js = next(h for h in hits if h.code == "688111")
    assert js._net_margin == pytest.approx(76.36, abs=0.1)
    assert js._gross_margin == pytest.approx(84.9)


def test_screen_share(monkeypatch):
    from ashare_monitor.screen import screen_share

    report = {
        # 白酒行业：茅台 923 + 五粮液 500 = 1423
        "600519": {"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                   "TOTAL_OPERATE_INCOME": 923e8, "PARENT_NETPROFIT": 445e8,
                   "BOARD_NAME": "白酒Ⅱ"},
        "000858": {"SECURITY_CODE": "000858", "SECURITY_NAME_ABBR": "五粮液",
                   "TOTAL_OPERATE_INCOME": 500e8, "PARENT_NETPROFIT": 200e8,
                   "BOARD_NAME": "白酒Ⅱ"},
        "000596": {"SECURITY_CODE": "000596", "SECURITY_NAME_ABBR": "古井贡酒",
                   "TOTAL_OPERATE_INCOME": 100e8, "PARENT_NETPROFIT": 30e8,
                   "BOARD_NAME": "白酒Ⅱ"},
        "600809": {"SECURITY_CODE": "600809", "SECURITY_NAME_ABBR": "山西汾酒",
                   "TOTAL_OPERATE_INCOME": 150e8, "PARENT_NETPROFIT": 50e8,
                   "BOARD_NAME": "白酒Ⅱ"},
        "000568": {"SECURITY_CODE": "000568", "SECURITY_NAME_ABBR": "泸州老窖",
                   "TOTAL_OPERATE_INCOME": 120e8, "PARENT_NETPROFIT": 60e8,
                   "BOARD_NAME": "白酒Ⅱ"},
        # 单股行业（样本<5 → 跳过）
        "601789": {"SECURITY_CODE": "601789", "SECURITY_NAME_ABBR": "宁波建工",
                   "TOTAL_OPERATE_INCOME": 97e8, "PARENT_NETPROFIT": 2.5e8,
                   "BOARD_NAME": "房屋建设Ⅱ"},
        # 行业字段缺失 → 跳过
        "600000": {"SECURITY_CODE": "600000", "SECURITY_NAME_ABBR": "浦发银行",
                   "TOTAL_OPERATE_INCOME": 1000e8, "PARENT_NETPROFIT": 300e8,
                   "BOARD_NAME": ""},
    }
    monkeypatch.setattr("ashare_monitor.screen._fetch_report_all",
                        lambda d: report)
    hits = screen_share(top_n=10, min_share=20.0, min_rev=10.0)
    codes = {h.code for h in hits}
    assert "600519" in codes and "000858" in codes
    assert "601789" not in codes     # 单股行业样本不足
    assert "600000" not in codes     # 行业缺失
    mt = next(h for h in hits if h.code == "600519")
    # 行业总营收 = 923+500+100+150+120 = 1793 → 923/1793 = 51.5%
    assert mt._share == pytest.approx(51.5, abs=0.1)
    assert mt._industry == "白酒Ⅱ"


def test_screen_lowval(monkeypatch):
    from ashare_monitor.screen import screen_lowval

    report = {
        "000001": {"SECURITY_CODE": "000001", "SECURITY_NAME_ABBR": "平安银行",
                   "PE_TTM": 5.1, "PB_MRQ": 0.47, "CLOSE_PRICE": 11.41,
                   "TOTAL_MARKET_CAP": 2214e8},
        "600519": {"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                   "PE_TTM": 22.0, "PB_MRQ": 7.0, "CLOSE_PRICE": 1450.0,
                   "TOTAL_MARKET_CAP": 1.8e12},
        "300999": {"SECURITY_CODE": "300999", "SECURITY_NAME_ABBR": "金龙鱼",
                   "PE_TTM": 60.0, "PB_MRQ": 3.0, "CLOSE_PRICE": 30.0,
                   "TOTAL_MARKET_CAP": 1600e8},   # PE>25 过滤
        "430282": {"SECURITY_CODE": "430282", "SECURITY_NAME_ABBR": "土友生物",
                   "PE_TTM": 3.0, "PB_MRQ": 0.5, "CLOSE_PRICE": 5.0,
                   "TOTAL_MARKET_CAP": 10e8},      # 北交所排除
    }
    monkeypatch.setattr("ashare_monitor.screen._fetch_valuation_all",
                        lambda d: report)
    hits = screen_lowval(top_n=10, max_pe=25.0, min_pe=5.0)
    codes = {h.code for h in hits}
    assert "000001" in codes
    assert "600519" not in codes      # PE 22 <25 应入选？PB 7 >5 被过滤
    assert "300999" not in codes      # PE 高
    assert "430282" not in codes      # 北交所
    assert hits[0].code == "000001"   # PE 最低排前


def test_screen_growth(monkeypatch):
    from ashare_monitor.screen import screen_growth

    report = {
        "301308": {"SECURITY_CODE": "301308", "SECURITY_NAME_ABBR": "江波龙",
                   "SJLTZ": 71528.7, "YSTZ": 136.3,
                   "TOTAL_OPERATE_INCOME": 200e8, "PARENT_NETPROFIT": 105.8e8},
        "600519": {"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
                   "SJLTZ": 15.0, "YSTZ": 12.0,
                   "TOTAL_OPERATE_INCOME": 900e8, "PARENT_NETPROFIT": 440e8},
        "600000": {"SECURITY_CODE": "600000", "SECURITY_NAME_ABBR": "浦发银行",
                   "SJLTZ": -10.0, "YSTZ": -5.0,
                   "TOTAL_OPERATE_INCOME": 1000e8, "PARENT_NETPROFIT": 300e8},
    }
    monkeypatch.setattr("ashare_monitor.screen._fetch_report_all",
                        lambda d: report)
    hits = screen_growth(top_n=10, min_growth=30.0)
    codes = {h.code for h in hits}
    assert "301308" in codes
    assert "600519" not in codes      # 增速 15 < 30
    assert "600000" not in codes      # 负增长
    j = hits[0]
    assert j._growth == pytest.approx(71528.7)


def test_fetch_growth_history(monkeypatch):
    from ashare_monitor.screen import fetch_growth_history

    report = {
        "002594": {"SECURITY_CODE": "002594", "SECURITY_NAME_ABBR": "比亚迪",
                   "YSTZ": 12.0, "SJLTZ": -19.0,
                   "TOTAL_OPERATE_INCOME": 7000e8, "PARENT_NETPROFIT": 380e8},
    }

    def fake(rd):
        return report if rd == "2025-12-31" else {}

    monkeypatch.setattr("ashare_monitor.screen._fetch_report_all", fake)
    monkeypatch.setattr("ashare_monitor.screen.datetime", __import__("datetime").datetime)
    rows = fetch_growth_history("002594", "比亚迪")
    by = {r.year: r for r in rows}
    assert 2025 in by
    assert by[2025].net_growth == pytest.approx(-19.0)
    assert by[2025].net_profit == pytest.approx(380.0)


def test_fetch_valuation_history(monkeypatch):
    from ashare_monitor.screen import fetch_valuation_history

    report = {
        "002594": {"SECURITY_CODE": "002594", "SECURITY_NAME_ABBR": "比亚迪",
                   "PE_TTM": 23.2, "PB_MRQ": 3.56, "CLOSE_PRICE": 90.0},
    }

    def fake(rd):
        return report

    monkeypatch.setattr("ashare_monitor.screen._fetch_valuation_all", fake)
    monkeypatch.setattr("ashare_monitor.screen._trade_date_around",
                        lambda d, lookback=10: f"{d[:4]}-12-31")
    monkeypatch.setattr("ashare_monitor.screen.datetime", __import__("datetime").datetime)
    rows = fetch_valuation_history("002594", "比亚迪")
    assert len(rows) >= 8  # 2018-2025+
    latest = rows[-1]
    assert latest.pe_ttm == pytest.approx(23.2)
    assert latest.year >= 2025


def test_build_screen_report():
    hits = [
        ScreenHit("601088", "中国神华", 38.9, 5.21, 12.5, 1.8, 7.73e11),
        ScreenHit("600900", "长江电力", 28.5, 3.85, 18.2, 3.1, 6.97e11),
    ]
    html, md = build_screen_report(hits, "高股息率",
                                   {"top": 60, "min_yield%": 3.0},
                                   as_of="2026-08-22")
    assert "高股息率选股" in html
    assert "中国神华" in html and "5.21" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 高股息率选股")


def test_screen_us_momentum(monkeypatch):
    import pandas as pd

    from ashare_monitor.screen import screen_us_momentum

    df = pd.DataFrame([
        {"代码": "NVDA", "名称": "英伟达", "最新价": 214.72, "涨跌幅": 3.2,
         "成交额": 9.9e7},
        {"代码": "AAPL", "名称": "苹果", "最新价": 230.0, "涨跌幅": 1.5,
         "成交额": 6.0e7},
        {"代码": "PENNY", "名称": "仙股", "最新价": 0.5, "涨跌幅": 50.0,
         "成交额": 1.0e5},   # 低价+小额过滤
        {"代码": "FALL", "名称": "下跌股", "最新价": 10.0, "涨跌幅": -5.0,
         "成交额": 1.0e8},   # 下跌排除
    ])
    monkeypatch.setattr("akshare.stock_us_spot_em",
                        lambda: df)
    hits = screen_us_momentum(top_n=5, min_turnover=1000.0, min_price=5.0)
    assert len(hits) == 2
    assert hits[0].code == "NVDA"
    assert hits[0].dividend_yield == pytest.approx(3.2)
