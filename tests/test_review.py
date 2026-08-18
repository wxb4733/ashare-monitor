"""复盘报告单元测试（不依赖网络）。"""

from datetime import datetime

from ashare_monitor.alerts import Alert
from ashare_monitor.main import _is_after_close
from ashare_monitor.quotes import Quote
from ashare_monitor.review import (
    append_alerts,
    build_html,
    load_alerts,
)


def make_alert(code="600519", rule="change_pct", profile="近120日 -11.8%") -> Alert:
    return Alert(
        code=code,
        name="贵州茅台",
        rule=rule,
        message="涨跌幅 -3.19%，超过阈值 ±3.0%",
        profile=profile,
        fired_at=datetime(2026, 8, 18, 10, 30, 15),
    )


def make_quote() -> Quote:
    return Quote(
        code="600519", name="贵州茅台", price=1290.69, change_pct=-0.19,
        change=-2.4, volume=22000, turnover=2.96e9, high=1298.86,
        low=1285.17, open=1291.0, prev_close=1293.09,
        timestamp=datetime(2026, 8, 18, 15, 0),
    )


# ---------- 预警持久化 ----------

def test_alerts_jsonl_roundtrip(tmp_path):
    directory = str(tmp_path)
    a1 = make_alert()
    a2 = make_alert(code="000001", rule="big_order", profile=None)
    a2.name = "平安银行"
    append_alerts([a1], "2026-08-18", directory)
    append_alerts([a2], "2026-08-18", directory)  # 追加不覆盖

    records = load_alerts("2026-08-18", directory)
    assert len(records) == 2
    assert records[0]["time"] == "10:30:15"
    assert records[0]["code"] == "600519"
    assert records[0]["profile"] == "近120日 -11.8%"
    assert records[1]["rule"] == "big_order"
    assert records[1]["profile"] is None
    # 不存在的日期返回空
    assert load_alerts("2026-08-19", directory) == []


# ---------- HTML 生成 ----------

def make_chart() -> dict:
    return {
        "id": "chart-600519",
        "title": "贵州茅台(600519) 近60日",
        "dates": ["2026-08-17", "2026-08-18"],
        "kdata": [[1290.0, 1293.09, 1285.0, 1300.0],
                  [1291.0, 1290.69, 1285.17, 1298.86]],
        "volumes": [25000, 22000],
    }


def test_build_html_sections():
    html = build_html(
        "2026-08-18",
        [make_quote()],
        [make_alert().to_dict()],
        [make_chart()],
    )
    assert "A 股收盘复盘报告" in html
    assert "2026-08-18" in html
    # 行情表
    assert "1290.69" in html and "-0.19%" in html
    assert "成交额" in html
    # 预警时间线：规则中文名 + 画像
    assert "涨跌幅" in html and "10:30:15" in html
    assert "波动画像：近120日 -11.8%" in html
    assert "共 1 条" in html
    # K 线图初始化调用
    assert 'renderKline("chart-600519"' in html
    assert "echarts" in html
    # 免责声明
    assert "不构成任何投资建议" in html


def test_build_html_no_alerts():
    html = build_html("2026-08-18", [make_quote()], [], [])
    assert "当日无预警记录" in html
    assert "共 0 条" in html


def test_quote_amplitude_in_table():
    html = build_html("2026-08-18", [make_quote()], [], [])
    # (1298.86-1285.17)/1293.09 ≈ 1.06%
    assert "1.06%" in html


# ---------- 收盘判定 ----------

def test_is_after_close():
    sessions = [["09:30", "11:30"], ["13:00", "15:00"]]
    assert _is_after_close(sessions, datetime(2026, 8, 18, 15, 1))    # 周二 15:01
    assert not _is_after_close(sessions, datetime(2026, 8, 18, 12, 0))  # 午休不触发
    assert not _is_after_close(sessions, datetime(2026, 8, 18, 14, 59))
    assert not _is_after_close(sessions, datetime(2026, 8, 15, 16, 0))  # 周六
