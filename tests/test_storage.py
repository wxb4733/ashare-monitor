"""SQLite 历史数据积累单元测试。"""

from datetime import datetime

import pytest

from ashare_monitor.alerts import Alert
from ashare_monitor.quotes import Quote
from ashare_monitor.storage import (
    count_alerts_by_code,
    count_alerts_by_rule,
    count_alerts_daily,
    count_news_by_code,
    load_announcements,
    load_alerts_range,
    load_research_reports,
    load_reviews_range,
    record_alerts,
    record_announcements,
    record_research_reports,
    save_review,
)


def make_alert(code="600519", rule="big_order", day="2026-08-18", hour="10:30") -> Alert:
    return Alert(
        code=code,
        name="贵州茅台",
        rule=rule,
        message=f"{rule} 触发",
        profile="近120日 -11.8%",
        fired_at=datetime.strptime(f"{day} {hour}:00", "%Y-%m-%d %H:%M:%S"),
    )


def make_quote() -> Quote:
    return Quote(
        code="600519", name="贵州茅台", price=1290.69, change_pct=-0.19,
        change=-2.4, volume=22000, turnover=2.96e9, high=1298.86,
        low=1285.17, open=1291.0, prev_close=1293.09,
        timestamp=datetime(2026, 8, 18, 15, 0),
    )


def test_alerts_roundtrip_and_aggregation(tmp_path):
    db = str(tmp_path / "test.db")
    record_alerts([
        make_alert(day="2026-08-17"),
        make_alert(day="2026-08-18", rule="amplitude"),
        make_alert(day="2026-08-18", rule="big_order", code="000001"),
        make_alert(day="2026-08-18", rule="big_order", code="000001"),
        make_alert(day="2026-08-19", rule="weibi"),
    ], market="ashare", db_path=db)

    # 范围查询
    rows = load_alerts_range("2026-08-18", "2026-08-18", db_path=db)
    assert len(rows) == 3
    assert rows[0]["code"] in ("000001", "600519")
    assert all(r["date"] == "2026-08-18" for r in rows)

    # 按规则聚合
    by_rule = count_alerts_by_rule("2026-08-01", "2026-08-31", db_path=db)
    mapping = {r["rule"]: r["count"] for r in by_rule}
    assert mapping["big_order"] == 3
    assert mapping["amplitude"] == 1

    # 按日聚合
    daily = count_alerts_daily("2026-08-01", "2026-08-31", db_path=db)
    assert {r["date"]: r["count"] for r in daily} == {
        "2026-08-17": 1, "2026-08-18": 3, "2026-08-19": 1,
    }

    # 按代码聚合（降序）：600519 共 3 条 > 000001 共 2 条
    by_code = count_alerts_by_code("2026-08-01", "2026-08-31", db_path=db)
    assert by_code[0]["code"] == "600519"
    assert by_code[0]["count"] == 3
    assert {r["code"]: r["count"] for r in by_code} == {"600519": 3, "000001": 2}

    # 空区间
    assert load_alerts_range("2020-01-01", "2020-01-02", db_path=db) == []


def test_review_save_and_load(tmp_path):
    db = str(tmp_path / "test.db")
    save_review(
        "2026-08-18", "output/review-2026-08-18.html",
        [make_quote()], [make_alert().to_dict()],
        db_path=db,
    )
    # 重复保存走 upsert
    save_review(
        "2026-08-18", "output/review-2026-08-18-v2.html",
        [make_quote()], [make_alert().to_dict()],
        db_path=db,
    )
    rows = load_reviews_range("2026-08-01", "2026-08-31", db_path=db)
    assert len(rows) == 1
    assert rows[0]["alert_count"] == 1
    assert rows[0]["report_path"].endswith("v2.html")
    assert rows[0]["quotes"][0]["code"] == "600519"
    assert rows[0]["quotes"][0]["change_pct"] == pytest.approx(-0.19)
    assert load_reviews_range("2020-01-01", "2020-01-02", db_path=db) == []


# ---------- 公告与研报存储 ----------

def test_announcements_upsert_and_load(tmp_path):
    db = str(tmp_path / "test.db")
    items = [
        {"date": "2026-08-15", "title": "业绩说明会公告", "url": "https://x/ann1"},
        {"date": "2026-08-10", "title": "半年报", "url": "https://x/ann2"},
    ]
    new, exist = record_announcements(items, "600519", name="贵州茅台", db_path=db)
    assert (new, exist) == (2, 0)
    # 重复入库去重
    new, exist = record_announcements(items, "600519", db_path=db)
    assert (new, exist) == (0, 2)
    # 新公告追加
    new, _ = record_announcements(
        [{"date": "2026-08-16", "title": "新公告", "url": "https://x/ann3"}],
        "600519", db_path=db,
    )
    assert new == 1

    rows = load_announcements("600519", db_path=db)
    assert len(rows) == 3
    assert rows[0]["title"] == "新公告"          # 日期倒序
    assert rows[0]["code"] == "600519"
    assert load_announcements("000001", db_path=db) == []


def test_research_reports_upsert_and_load(tmp_path):
    db = str(tmp_path / "test.db")
    items = [
        {"date": "2026-08-18", "title": "短期业绩承压", "org": "山西证券",
         "eps_this_year": 68.21, "pe_this_year": 18.1, "url": "https://x/r1"},
        {"date": "2026-08-01", "title": "渠道改革", "org": "中金",
         "eps_this_year": None, "pe_this_year": None, "url": "https://x/r2"},
    ]
    new, exist = record_research_reports(items, "600519", name="贵州茅台", db_path=db)
    assert (new, exist) == (2, 0)
    new, exist = record_research_reports(items, "600519", db_path=db)
    assert (new, exist) == (0, 2)

    rows = load_research_reports("600519", db_path=db)
    assert len(rows) == 2
    first = rows[0]
    assert first["org"] == "山西证券" and first["eps_this_year"] == 68.21
    assert rows[1]["eps_this_year"] is None
    assert load_research_reports("000001", db_path=db) == []


def test_count_news_by_code(tmp_path):
    db = str(tmp_path / "test.db")
    record_announcements(
        [{"date": "2026-08-15", "title": "a1", "url": "https://x/a1"},
         {"date": "2026-08-10", "title": "a2", "url": "https://x/a2"}],
        "600519", db_path=db,
    )
    record_research_reports(
        [{"date": "2026-08-18", "title": "r1", "url": "https://x/r1"}],
        "600519", db_path=db,
    )
    record_announcements(
        [{"date": "2026-08-15", "title": "b1", "url": "https://x/b1"}],
        "000001", db_path=db,
    )
    stats = count_news_by_code(db_path=db)
    mapping = {s["code"]: s for s in stats}
    assert mapping["600519"]["anns"] == 2 and mapping["600519"]["reports"] == 1
    assert mapping["000001"]["anns"] == 1 and mapping["000001"]["reports"] == 0
    assert stats[0]["code"] == "600519"   # 总数降序
