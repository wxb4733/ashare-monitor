"""政府侧企业动态单元测试（mock 公告）。"""

import pytest

from ashare_monitor.gov import (
    GovItem,
    build_gov_report,
    classify_title,
    scan_government_dynamics,
)


def test_classify_title():
    assert classify_title("关于公司中标某项目的公告") == ("招投标", "中标")
    assert classify_title("关于竞得土地使用权的公告") == ("拿地", "土地使用权")
    assert classify_title("获得政府补助的公告") == ("补助补贴", "政府补助")
    assert classify_title("通过高新技术企业认定的公告") == ("资质税收", "高新技术企业")
    assert classify_title("2025年年度报告") is None


def test_scan_government_dynamics(monkeypatch):
    monkeypatch.setattr(
        "ashare_monitor.announcements.fetch_announcements",
        lambda code, limit=30: [
            {"date": "2026-08-10", "title": "关于收到政府补助的公告",
             "url": "http://x/1"},
            {"date": "2026-08-05", "title": "2025年年度股东大会决议公告",
             "url": "http://x/2"},
            {"date": "2026-08-01", "title": "关于竞得土地使用权的公告",
             "url": "http://x/3"},
        ],
    )

    class _Cfg:
        watchlist = [
            {"code": "002594", "market": "ashare", "name": "比亚迪"},
            {"code": "01211", "market": "hk", "name": "比亚迪股份"},
        ]

    items = scan_government_dynamics(_Cfg())
    assert len(items) == 2  # 港股跳过 + 无关公告过滤
    cats = {x.category for x in items}
    assert cats == {"补助补贴", "拿地"}
    assert items[0].title.startswith("关于收到政府补助")


def test_build_gov_report():
    items = [
        GovItem("002594", "比亚迪", "2026-08-10", "关于收到政府补助的公告",
                "补助补贴", "http://x/1", "政府补助"),
        GovItem("300750", "宁德时代", "2026-08-01", "关于竞得土地使用权的公告",
                "拿地", "http://x/3", "土地使用权"),
    ]
    html, md = build_gov_report(items, 30, as_of="2026-08-21")
    assert "政府侧企业动态" in html
    assert "补助补贴" in html and "拿地" in html
    assert "比亚迪" in html and "宁德时代" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 政府动态")
