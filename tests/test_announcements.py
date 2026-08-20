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


# ---------- 重大事项识别 ----------

def test_is_major_keywords():
    from ashare_monitor.announcements import is_major

    majors = [
        "2026年半年度业绩预告", "关于2025年度利润分配预案的公告",
        "重大资产重组停牌公告", "2026年第一季度报告", "股东减持股份计划",
        "关于收到立案告知书的公告", "回购公司股份方案", "可转换公司债券发行",
    ]
    normals = [
        "关于日常关联交易的公告", "投资者关系活动记录表",
        "关于使用闲置资金理财的公告", "公司章程修订说明",
    ]
    for t in majors:
        assert is_major(t), t
    for t in normals:
        assert not is_major(t), t


def test_build_html_major_announcement_first():
    from ashare_monitor.review import build_html

    news = [
        {"kind": "ann", "code": "600519", "name": "贵州茅台",
         "date": "2026-08-18", "title": "日常关联交易公告", "url": "https://x/1"},
        {"kind": "ann", "code": "600519", "name": "贵州茅台",
         "date": "2026-08-19", "title": "2026年半年度业绩预告", "url": "https://x/2"},
        {"kind": "report", "code": "600519", "name": "贵州茅台",
         "date": "2026-08-18", "title": "研报标题", "url": "https://x/3", "org": "山西证券"},
    ]
    html = build_html("2026-08-20", [], [], [], news_rows=news)
    # 重大事项标红 + 置顶（业绩预告应出现在日常公告之前）
    assert "★重大·公告" in html
    assert "color:#e02e24;font-weight:600\">2026年半年度业绩预告" in html
    assert html.index("2026年半年度业绩预告") < html.index("日常关联交易公告")
    # 研报不受影响
    assert "山西证券" in html
