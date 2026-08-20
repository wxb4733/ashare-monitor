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


# ---------- IPO 分析报告 ----------

def make_records() -> list:
    from ashare_monitor.ipo import IPORecord

    return [
        IPORecord(
            code="301689", name="电科思仪", market="深圳证券交易所",
            industry="仪器仪表", apply_date="2026-08-28", listing_date="",
            issue_price=None, issue_pe=None, industry_pe=61.9,
            raise_funds=None, plan_funds=10.0, issue_num=None,
            main_business="电子测量仪器", underwriter="", newest_price=None,
        ),
        IPORecord(
            code="601123", name="马矿股份", market="上海证券交易所",
            industry="钢铁", apply_date="2026-08-21", listing_date="",
            issue_price=6.65, issue_pe=None, industry_pe=36.1,
            raise_funds=8.21, plan_funds=10.0, issue_num=None,
            main_business="铁矿石采选与铁精粉销售", underwriter="中信证券",
            newest_price=None,
        ),
        IPORecord(
            code="301688", name="格林生物", market="深圳证券交易所",
            industry="化工", apply_date="2026-08-20", listing_date="2026-08-18",
            issue_price=26.33, issue_pe=None, industry_pe=28.0,
            raise_funds=8.78, plan_funds=8.0, issue_num=None,
            main_business="香料香精", underwriter="", newest_price=24.0,
        ),
    ]


def test_build_ipo_report():
    from ashare_monitor.ipo import build_ipo_report

    html, md = build_ipo_report(make_records(), as_of="2026-08-20")
    # HTML 结构
    assert "IPO 分析报告" in html
    assert "近期新股日历" in html
    assert "电科思仪" in html and "马矿股份" in html and "格林生物" in html
    assert "重点新股分析" in html
    assert "破发提示" in html                    # 格林生物 24.0 < 26.33
    assert "待申购" in html and "待上市" in html
    assert "不构成投资建议" in html
    # 破发计算：24.0/26.33 - 1 = -8.85%
    assert "-8.85%" in html or "-8.8%" in html
    # Markdown 结构
    assert md.startswith("---\ntitle: IPO分析报告 2026-08-20")
    assert "tags: [IPO, A股]" in md
    assert "| 301689 | 电科思仪 |" in md
    assert "## 重点新股分析" in md
    assert "## 破发提示" in md
    assert "不构成投资建议" in md


def test_build_ipo_report_no_focus():
    from ashare_monitor.ipo import IPORecord, build_ipo_report

    # 全是已上市且未破发 → 无重点分析、无破发提示
    recs = [
        IPORecord(code="600001", name="示例", market="上海证券交易所",
                  industry="", apply_date="2026-08-01", listing_date="2026-08-10",
                  issue_price=10.0, issue_pe=None, industry_pe=None,
                  raise_funds=5.0, plan_funds=None, issue_num=None,
                  main_business="", underwriter="", newest_price=12.0),
    ]
    html, md = build_ipo_report(recs, as_of="2026-08-20")
    assert "重点新股分析" not in html
    assert "破发提示" not in html
    assert "已上市" in html
    assert "重点新股分析" not in md
    assert "破发提示" not in md


# ---------- 历史 IPO ----------

def test_parse_ipo_history_item():
    from ashare_monitor.ipo import _parse_ipo_history_item

    item = {
        "SECURITY_CODE": "002594", "SECURITY_NAME_ABBR": "比亚迪",
        "TRADE_MARKET": "深圳证券交易所", "LISTING_DATE": "2011-06-30 00:00:00",
        "APPLY_DATE": "2011-06-21 00:00:00", "ISSUE_PRICE": 18.0,
        "AFTER_ISSUE_PE": 20.47, "INDUSTRY_PE_NEW": 22.79,
        "TOTAL_RAISE_FUNDS": 14.22, "PREDICT_RAISE_FUNDS": 21.924,
        "TOTAL_ISSUE_NUM": 7900, "MAIN_BUSINESS": "新能源汽车与电池",
        "UNDERWRITER_ORG": "瑞银证券", "CLOSE_PRICE": 25.45,
        "LD_CLOSE_CHANGE": 41.39, "LD_HIGH_CHANG": 45.5,
        "LD_OPEN_PREMIUM": 22.22, "AMPLITUDE": 23.28,
        "TNEW_PRICE": 90.4, "TCHANGE_RATE": 402.22,
    }
    r = _parse_ipo_history_item(item)
    assert r["code"] == "002594" and r["listing_date"] == "2011-06-30"
    assert r["issue_price"] == 18.0 and r["issue_pe"] == 20.47
    assert r["first_day_change"] == 41.39 and r["first_day_close"] == 25.45
    assert r["newest_price"] == 90.4 and r["newest_change"] == 402.22


def test_build_ipo_history_report():
    from ashare_monitor.ipo import build_ipo_history_report

    a = {
        "code": "002594", "name": "比亚迪", "market": "深圳证券交易所",
        "listing_date": "2011-06-30", "apply_date": "2011-06-21",
        "issue_price": 18.0, "issue_pe": 20.47, "industry_pe": 22.79,
        "raise_funds": 14.22, "plan_funds": 21.924, "issue_num": 7900.0,
        "issue_num_note": "", "raise_note": "", "pe_note": "",
        "main_business": "新能源汽车", "underwriter": "瑞银证券",
        "first_day_close": 25.45, "first_day_change": 41.39,
        "first_day_high_chg": 45.5, "first_day_open_premium": 22.22,
        "amplitude": 23.28, "newest_price": 90.4, "newest_change": 402.22,
        "note": "", "source": "东财",
    }
    hk = {
        "code": "01211", "name": "比亚迪股份", "market": "香港联交所主板",
        "listing_date": "2002-07-31", "apply_date": "",
        "issue_price": 10.95, "issue_pe": 8.5, "industry_pe": None,
        "raise_funds": 16.37, "plan_funds": None, "issue_num": 14950.0,
        "issue_num_note": "含超额配售", "raise_note": "亿港元", "pe_note": "按2002净利估算",
        "main_business": "二次充电电池", "underwriter": "",
        "first_day_close": None, "first_day_change": None,
        "first_day_high_chg": None, "first_day_open_premium": None,
        "amplitude": None, "newest_price": 89.4, "newest_change": 716.44,
        "note": "当时H股最高发行价", "source": "公司公告",
    }
    html, md = build_ipo_history_report([a, hk], as_of="2026-08-20")
    assert "BYD A股/港股 IPO 发行分析" in html
    assert "比亚迪(002594)" in html and "比亚迪股份(01211)" in html
    assert "首日收盘 25.45" in html
    assert "+41.39%" in html
    assert "缩募" in html                       # 14.22/21.92 完成 65%
    assert "发行 PE 低于行业 PE" in html          # 20.47/22.79 < 0.9
    assert "当时H股最高发行价" in html
    assert "上市首日不复权明细缺失" in html         # 港股诚实标注
    assert "最新价 89.40" in html or "最新价 89.4" in html
    assert "不构成投资建议" in html
    # Markdown
    assert md.startswith("---\ntitle: BYD A股/港股 IPO 发行分析")
    assert "## 比亚迪(002594)" in md and "## 比亚迪股份(01211)" in md
    assert "| 发行价 | 18.00 元 |" in md
