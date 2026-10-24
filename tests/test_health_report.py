# -*- coding: utf-8 -*-
"""scripts/health_report.py 纯函数单测（不触库、不联网）。"""
from datetime import date

from scripts.health_report import (last_weekday_on_or_before, nav_points,
                                   tier, weekdays_between)


def test_weekdays_between_excludes_start_includes_end():
    got = weekdays_between(date(2026, 10, 21), date(2026, 10, 23))
    assert got == [date(2026, 10, 22), date(2026, 10, 23)]


def test_weekdays_between_skips_weekend():
    got = weekdays_between(date(2026, 10, 16), date(2026, 10, 19))
    assert got == [date(2026, 10, 19)]  # 10-17/18 周末跳过


def test_last_weekday_on_or_before_weekend():
    assert last_weekday_on_or_before(date(2026, 10, 24)) == date(2026, 10, 23)  # 周六→周五
    assert last_weekday_on_or_before(date(2026, 10, 25)) == date(2026, 10, 23)  # 周日→周五


def test_nav_points_shape_and_values():
    nav = [["2026-01-05", 1.0], ["2026-01-06", 1.05], ["2026-01-07", 1.02]]
    lab, rng = nav_points(nav)
    pts = lab["polyline"].split()
    assert len(pts) == 3
    assert lab["peak_d"] == "2026-01-06" and lab["peak_v"] == "1.0500"
    assert lab["last_v"] == "1.0200"
    # y 越小净值越高：峰值 y 应小于终点 y
    assert float(pts[1].split(",")[1]) < float(pts[2].split(",")[1])
    assert rng["first_d"] == "2026-01-05"


def test_tier_boundaries():
    today = date(2026, 10, 23)
    assert tier("2026-10-21", today) == "fresh"   # 2 天
    assert tier("2026-10-08", today) == "mid"     # 15 天
    assert tier("2026-10-05", today) == "mid"     # 18 天（20 天边界内）
    assert tier("2026-10-01", today) == "stale"   # 22 天
    assert tier("2026-09-30", today) == "stale"   # 23 天
    assert tier(None, today) == "stale"
