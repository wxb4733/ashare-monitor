"""财报分析单元测试（合成 JSON，不依赖网络）。"""

import pytest

from ashare_monitor.fundamentals import (
    FinancialPeriod,
    parse_financials,
    summarize,
)


def make_financial_json() -> list[dict]:
    return [
        {
            "SECURITY_CODE": "600519",
            "SECURITY_NAME_ABBR": "贵州茅台",
            "REPORTDATE": "2026-06-30 00:00:00",
            "TOTAL_OPERATE_INCOME": 92278072083.21,   # 922.78 亿
            "PARENT_NETPROFIT": 44516880421.86,       # 445.17 亿
            "YSTZ": 1.30,        # 营收同比
            "SJLTZ": -1.95,      # 净利同比
            "WEIGHTAVG_ROE": 16.75,
            "BASIC_EPS": 35.57,
            "XSMLL": 89.56,
            "MGJYXJJE": 56.55,
        },
        {
            "REPORTDATE": "2026-03-31 00:00:00",
            "TOTAL_OPERATE_INCOME": 50000000000.0,    # 500 亿
            "PARENT_NETPROFIT": 25000000000.0,        # 250 亿
            "YSTZ": 2.50,
            "SJLTZ": 3.10,
            "WEIGHTAVG_ROE": 8.90,
            "BASIC_EPS": 19.90,
            "XSMLL": 91.20,
            "MGJYXJJE": 20.00,
        },
        {
            "REPORTDATE": "2025-12-31 00:00:00",
            "TOTAL_OPERATE_INCOME": 1500000000000.0,  # 1.5 万亿
            "PARENT_NETPROFIT": 700000000000.0,       # 7000 亿
            "YSTZ": 3.00,
            "SJLTZ": 4.20,
            "WEIGHTAVG_ROE": 28.00,
            "BASIC_EPS": 55.70,
            "XSMLL": 90.50,
            "MGJYXJJE": 60.00,
        },
    ]


def test_parse_financials():
    items = parse_financials(make_financial_json())
    assert len(items) == 3
    latest = items[0]
    assert latest.report_date == "2026-06-30"
    assert latest.revenue == pytest.approx(922.78, rel=0.01)      # 元 → 亿
    assert latest.net_profit == pytest.approx(445.17, rel=0.01)
    assert latest.revenue_yoy == pytest.approx(1.30)
    assert latest.profit_yoy == pytest.approx(-1.95)
    assert latest.roe == pytest.approx(16.75)
    assert latest.gross_margin == pytest.approx(89.56)
    # 净利率 = 归母净利 / 营收
    assert latest.net_margin == pytest.approx(445.17 / 922.78 * 100, rel=0.01)
    assert latest.eps == pytest.approx(35.57)
    assert latest.ocf_per_share == pytest.approx(56.55)
    # 年份报表（1.5 万亿营收）换算正确
    assert items[2].revenue == pytest.approx(15000.0, rel=0.01)


def test_parse_financials_missing_fields():
    items = parse_financials([
        {"REPORTDATE": "2026-06-30 00:00:00", "TOTAL_OPERATE_INCOME": None},
        {},
    ])
    assert items[0].revenue is None and items[0].profit_yoy is None
    assert items[0].net_margin is None
    assert items[1].report_date == ""          # 缺报告期
    assert parse_financials([]) == []


def test_summarize_growth():
    items = parse_financials(make_financial_json())
    lines = summarize(items)
    text = "\n".join(lines)
    assert "最新期营收同比 +1.3%" in text
    assert "净利同比 -1.9%" in text
    # 最新期净利同比 -1.95 vs 上期 +3.10 → 环比放缓
    assert "净利增速环比放缓" in text
    # 近 3 期净利同比 3.10/4.20 为正，但最新期 -1.95 → 不满足连续正增长
    assert "连续正增长" not in text
    # ROE ≥ 15 → 优秀
    assert "ROE 16.8%（优秀" in text
    # 每股经营现金流 56.55 > EPS 35.57 → 盈利质量好
    assert "盈利质量好" in text


def test_summarize_three_negative():
    items = [
        FinancialPeriod("2026-06-30", 100, 10, -5.0, -8.0, 6.0, 30.0, 10.0, 1.0, 0.5),
        FinancialPeriod("2026-03-31", 110, 12, -3.0, -6.0, 7.0, 30.0, 10.9, 1.2, 0.6),
        FinancialPeriod("2025-12-31", 120, 14, -2.0, -5.0, 8.0, 30.0, 11.7, 1.4, 0.8),
    ]
    lines = summarize(items)
    assert any("连续负增长" in line for line in lines)
    assert any("ROE 6.0%（偏低）" in line for line in lines)


def test_summarize_empty():
    assert summarize([]) == []


# ---------- 港股财报 ----------

def test_parse_financials_hk():
    from ashare_monitor.fundamentals import parse_financials_hk

    data = [{
        "REPORT_DATE": "2025-12-31 00:00:00",
        "OPERATE_INCOME": 803964958000,       # 港元原值 → 8039.65 亿
        "OPERATE_INCOME_YOY": 3.456752,
        "HOLDER_PROFIT": 32619022000,         # → 326.19 亿
        "HOLDER_PROFIT_YOY": -18.967701,
        "GROSS_PROFIT_RATIO": 17.744529,
        "NET_PROFIT_RATIO": 4.199282,
        "ROE_AVG": 15.117997,
        "BASIC_EPS": 3.58,
        "PER_NETCASH_OPERATE": 6.486154,
    }]
    ps = parse_financials_hk(data)
    assert len(ps) == 1
    p = ps[0]
    assert p.report_date == "2025-12-31"
    assert p.revenue == pytest.approx(8039.65)
    assert p.net_profit == pytest.approx(326.19)
    assert p.revenue_yoy == pytest.approx(3.456752)
    assert p.profit_yoy == pytest.approx(-18.967701)
    assert p.gross_margin == pytest.approx(17.744529)
    assert p.roe == pytest.approx(15.117997)
    assert p.eps == pytest.approx(3.58)
    assert p.ocf_per_share == pytest.approx(6.486154)
    # 净利率：有接口字段直接用，无则按 净利/营收 计算
    assert p.net_margin == pytest.approx(4.199282)


def test_parse_financials_hk_net_margin_computed():
    from ashare_monitor.fundamentals import parse_financials_hk

    data = [{
        "REPORT_DATE": "2024-12-31 00:00:00",
        "OPERATE_INCOME": 100000000000.0,     # 1000 亿
        "HOLDER_PROFIT": 10000000000.0,       # 100 亿
        # NET_PROFIT_RATIO 缺失 → 用 净利/营收 计算 = 10%
    }]
    p = parse_financials_hk(data)[0]
    assert p.net_margin == pytest.approx(10.0)
    assert p.revenue == pytest.approx(1000.0)
    assert p.profit_yoy is None
