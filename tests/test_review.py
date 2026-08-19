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


# ---------- 大盘指数板块与推送摘要 ----------

def make_index_quote() -> Quote:
    return Quote(
        code="000001", name="上证指数", price=3968.95, change_pct=-0.34,
        change=-13.6, volume=0, turnover=6.5e11, high=3990.0,
        low=3954.0, open=3980.0, prev_close=3982.55,
        timestamp=datetime(2026, 8, 18, 15, 0),
    )


def test_build_html_with_index_section():
    html = build_html(
        "2026-08-18",
        [make_quote()],
        [make_alert().to_dict()],
        [make_chart()],
        index_quotes=[make_index_quote()],
        index_charts=[{**make_chart(), "id": "chart-000001-idx", "title": "上证指数"}],
    )
    # 指数板块存在且章节编号顺延
    assert "一、大盘指数" in html
    assert "二、自选股当日表现" in html
    assert "三、当日预警时间线" in html
    assert "上证指数" in html and "3,968.95" in html
    assert 'renderKline("chart-000001-idx"' in html
    # 无指数时保持原章节编号
    html2 = build_html("2026-08-18", [make_quote()], [], [])
    assert "一、自选股当日表现" in html2
    assert "大盘指数" not in html2


def test_build_push_summary():
    from ashare_monitor.review import build_push_summary

    text = build_push_summary(
        "2026-08-18", [make_quote()], [make_alert().to_dict()], "output/review-2026-08-18.html"
    )
    assert "A 股复盘 2026-08-18" in text
    assert "贵州茅台(600519) 1290.69 -0.19%" in text
    assert "当日预警 1 条" in text
    assert "review-2026-08-18.html" in text


# ---------- 技术指标板块 ----------

def test_build_html_indicator_section():
    ind_rows = [
        {
            "code": "600519", "name": "贵州茅台", "market": "ashare",
            "summary": "MACD死叉(2日前) | RSI 48 | KDJ死叉 | BOLL中下",
            "macd": "死叉(2日前)", "rsi": "48", "kdj": "死叉", "boll": "中下",
        },
    ]
    html = build_html(
        "2026-08-18",
        [make_quote()],
        [make_alert().to_dict()],
        [make_chart()],
        indicator_rows=ind_rows,
    )
    # 指标板块存在，章节编号顺延（无公告时 K 线紧随其后）
    assert "一、技术指标状态" in html
    assert "二、自选股当日表现" in html
    assert "三、当日预警时间线" in html
    assert "四、近期 K 线走势" in html
    assert "死叉(2日前)" in html and "48" in html and "BOLL" in html
    # 无指标时保持原编号
    html2 = build_html("2026-08-18", [make_quote()], [], [])
    assert "一、自选股当日表现" in html2
    assert "技术指标状态" not in html2


def test_build_html_news_section():
    ind_rows = [{
        "code": "600519", "name": "贵州茅台", "market": "ashare",
        "summary": "MACD死叉 | RSI 48 | KDJ死叉 | BOLL中下",
        "macd": "死叉", "rsi": "48", "kdj": "死叉", "boll": "中下",
    }]
    news = [
        {"kind": "ann", "code": "600519", "name": "贵州茅台",
         "date": "2026-08-15", "title": "关于召开业绩说明会的公告",
         "url": "https://example.com/ann"},
        {"kind": "report", "code": "600519", "name": "贵州茅台",
         "date": "2026-08-18", "title": "短期业绩承压，i茅台延续高增",
         "url": "https://example.com/report", "org": "山西证券"},
    ]
    html = build_html(
        "2026-08-18", [make_quote()], [], [make_chart()],
        indicator_rows=ind_rows, news_rows=news,
    )
    assert "四、公告与研报" in html
    assert "五、近期 K 线走势" in html
    assert "公告" in html and "研报" in html
    assert "山西证券" in html
    assert 'href="https://example.com/ann"' in html
    # 无公告时 K 线编号顺延回来
    html2 = build_html("2026-08-18", [make_quote()], [], [],
                       indicator_rows=ind_rows)
    assert "四、近期 K 线走势" in html2
