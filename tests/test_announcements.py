"""公告与研报解析单元测试（合成 JSON，不依赖网络）。"""

from ashare_monitor.announcements import (
    parse_announcements,
    parse_research_reports,
)


def make_announcement_json() -> dict:
    return {
        "data": {
            "list": [
                {
                    "art_code": "AN202608141827994407",
                    "notice_date": "2026-08-15 00:00:00",
                    "title": "贵州茅台:贵州茅台关于召开2026年半年度业绩说明会的公告",
                },
                {
                    "art_code": "AN202608101234567890",
                    "notice_date": "2026-08-10 00:00:00",
                    "title": "600519:贵州茅台2026年半年度报告",
                },
            ]
        }
    }


def make_report_json() -> dict:
    return {
        "hits": 2,
        "data": [
            {
                "title": "短期业绩承压，i茅台延续高增",
                "orgSName": "山西证券",
                "publishDate": "2026-08-18 00:00:00.000",
                "infoCode": "AP202608181828111071",
                "predictThisYearEps": "68.2100000000",
                "predictNextYearPe": "18.1000000000",
                "predictNextTwoYearEps": "75.1100000000",
            },
            {
                "title": "茅台渠道改革效果显现",
                "orgSName": "中金公司",
                "publishDate": "2026-08-01 00:00:00.000",
                "infoCode": "AP202608010000000000",
                "predictThisYearEps": None,
                "predictNextYearPe": None,
            },
        ],
    }


def test_parse_announcements():
    items = parse_announcements(make_announcement_json())
    assert len(items) == 2
    first = items[0]
    assert first["date"] == "2026-08-15"
    # 去掉 "贵州茅台:" 前缀
    assert first["title"].startswith("贵州茅台关于召开")
    assert "art_code=AN202608141827994407" in first["url"]
    # 第二条保留"600519:" 后的内容
    assert items[1]["title"] == "贵州茅台2026年半年度报告"


def test_parse_announcements_empty():
    assert parse_announcements({"data": {"list": []}}) == []
    assert parse_announcements({}) == []


def test_parse_research_reports():
    items = parse_research_reports(make_report_json())
    assert len(items) == 2
    first = items[0]
    assert first["date"] == "2026-08-18"
    assert first["org"] == "山西证券"
    assert first["title"] == "短期业绩承压，i茅台延续高增"
    assert first["eps_this_year"] == 68.21
    assert first["pe_this_year"] == 18.1
    assert "AP202608181828111071" in first["url"]
    # 缺失预测字段 → None
    assert items[1]["eps_this_year"] is None
    assert items[1]["pe_this_year"] is None


def test_parse_research_reports_empty():
    assert parse_research_reports({"data": []}) == []
    assert parse_research_reports({}) == []
