"""IPO 分析单元测试（合成 JSON，不依赖网络）。"""

from datetime import datetime

import pytest

from ashare_monitor.ipo import (
    IPORecord,
    analyze_ipo,
    find_ipo,
    parse_ipo_list,
)


def make_ipo_data() -> list[dict]:
    return [
        {
            "SECURITY_CODE": "301689",
            "SECURITY_NAME_ABBR": "电科思仪",
            "TRADE_MARKET": "深圳证券交易所",
            "INDUSTRY_NAME": "仪器仪表制造业",
            "APPLY_DATE": "2026-08-28 00:00:00",
            "LISTING_DATE": None,
            "ISSUE_PRICE": None,
            "PREDICT_ISSUE_PE": None,
            "INDUSTRY_PE_NEW": 32.5,
            "TOTAL_RAISE_FUNDS": None,
            "PREDICT_RAISE_FUNDS": 12.0,
            "TOTAL_ISSUE_NUM": 10206.94,
            "MAIN_BUSINESS": "电子测量仪器",
            "UNDERWRITER_ORG": "招商证券股份有限公司",
            "NEWEST_PRICE": None,
        },
        {
            "SECURITY_CODE": "601123",
            "SECURITY_NAME_ABBR": "马矿股份",
            "TRADE_MARKET": "上海证券交易所",
            "INDUSTRY_NAME": "黑色金属矿采选业",
            "APPLY_DATE": "2026-08-21 00:00:00",
            "LISTING_DATE": None,
            "ISSUE_PRICE": 6.65,
            "PER_SHARES_INCOME": 0.3,     # 发行PE ≈ 22.2
            "INDUSTRY_PE_NEW": 36.09,
            "TOTAL_RAISE_FUNDS": 8.21,
            "PREDICT_RAISE_FUNDS": 10.0,
            "TOTAL_ISSUE_NUM": 12350.0,
            "MAIN_BUSINESS": "铁矿石的采选、综合利用及铁精粉、钼精矿销售",
            "UNDERWRITER_ORG": "中信证券股份有限公司",
            "NEWEST_PRICE": None,
        },
        {
            "SECURITY_CODE": "600001",
            "SECURITY_NAME_ABBR": "老新股",
            "TRADE_MARKET": "上海证券交易所",
            "INDUSTRY_NAME": "钢铁",
            "APPLY_DATE": "2026-06-01 00:00:00",
            "LISTING_DATE": "2026-07-01 00:00:00",
            "ISSUE_PRICE": 10.0,
            "PER_SHARES_INCOME": 1.0,
            "INDUSTRY_PE_NEW": 20.0,
            "TOTAL_RAISE_FUNDS": 5.0,
            "PREDICT_RAISE_FUNDS": 5.0,
            "TOTAL_ISSUE_NUM": 5000.0,
            "MAIN_BUSINESS": "钢铁冶炼",
            "UNDERWRITER_ORG": "国泰君安",
            "NEWEST_PRICE": 8.5,           # 已破发
        },
    ]


def test_parse_ipo_list():
    items = parse_ipo_list(make_ipo_data())
    assert len(items) == 3
    pending = items[0]
    assert pending.code == "301689" and pending.name == "电科思仪"
    assert pending.issue_price is None and pending.issue_pe is None
    assert pending.apply_date == "2026-08-28"

    priced = items[1]
    assert priced.issue_price == 6.65
    assert priced.issue_pe == pytest.approx(6.65 / 0.3, rel=0.01)  # ≈22.2
    assert priced.industry_pe == 36.09
    assert priced.pe_ratio == pytest.approx(6.65 / 0.3 / 36.09, rel=0.01)
    assert priced.raise_funds == 8.21 and priced.plan_funds == 10.0

    listed = items[2]
    assert listed.newest_price == 8.5


def test_stage_detection():
    items = parse_ipo_list(make_ipo_data())
    now = datetime(2026, 8, 20, 10, 0)
    assert items[0].stage(now) == "待定价"       # 未定价
    assert items[1].stage(now) == "待申购"       # 8/21 申购
    assert items[2].stage(now) == "已上市"       # 有最新价
    # 8/22 之后马矿进入待上市
    assert items[1].stage(datetime(2026, 8, 22, 10, 0)) == "待上市"


def test_find_ipo():
    items = parse_ipo_list(make_ipo_data())
    assert find_ipo(items, "601123").name == "马矿股份"    # 代码精确
    assert find_ipo(items, "马矿").code == "601123"        # 名称包含
    assert find_ipo(items, "不存在") is None


def test_analyze_ipo_pending_pricing():
    items = parse_ipo_list(make_ipo_data())
    lines = analyze_ipo(items[0], datetime(2026, 8, 20, 10, 0))
    assert any("尚未定价" in line for line in lines)
    assert any("电科思仪" not in line for line in lines)  # 主营独立成行
    assert any("主营" in line for line in lines)


def test_analyze_ipo_pe_comparison():
    items = parse_ipo_list(make_ipo_data())
    lines = analyze_ipo(items[1], datetime(2026, 8, 20, 10, 0))
    # 发行PE 22.2 < 行业 36.09 → 估值相对便宜
    assert any("低于行业" in line for line in lines)
    assert any("缩募" in line for line in lines)           # 8.21 < 10 亿
    assert any("保荐机构" in line for line in lines)


def test_analyze_ipo_break():
    items = parse_ipo_list(make_ipo_data())
    lines = analyze_ipo(items[2])
    assert any("已破发" in line for line in lines)


def test_ipo_record_defaults():
    rec = IPORecord("000001", "", "", "", "", "", None, None, None, None, None, None, "", "", None)
    assert rec.stage() == "待定价"
    assert rec.pe_ratio is None
