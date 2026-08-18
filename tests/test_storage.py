"""SQLite 历史数据积累单元测试。"""

from datetime import datetime

import pytest

from ashare_monitor.alerts import Alert
from ashare_monitor.quotes import Quote
from ashare_monitor.storage import (
    count_alerts_by_code,
    count_alerts_by_rule,
    count_alerts_daily,
    load_alerts_range,
    load_reviews_range,
    record_alerts,
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
