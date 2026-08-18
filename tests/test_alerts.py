"""预警引擎单元测试。"""

from datetime import datetime

from ashare_monitor.alerts import AlertEngine
from ashare_monitor.config import AlertConfig
from ashare_monitor.quotes import Quote, is_trading_time


def make_quote(code="600519", price=1700.0, change_pct=3.5) -> Quote:
    return Quote(
        code=code,
        name="测试股",
        price=price,
        change_pct=change_pct,
        change=10.0,
        volume=1000,
        turnover=1e8,
        high=price,
        low=price - 20,
        open=price - 10,
        prev_close=price - 10,
        timestamp=datetime.now(),
    )


def test_change_pct_alert_triggers():
    engine = AlertEngine(AlertConfig(change_pct_threshold=3.0))
    alerts = engine.check(make_quote(change_pct=3.5))
    assert len(alerts) == 1
    assert alerts[0].rule == "change_pct"


def test_change_pct_below_threshold_no_alert():
    engine = AlertEngine(AlertConfig(change_pct_threshold=3.0))
    assert engine.check(make_quote(change_pct=1.0)) == []


def test_alert_cooldown_no_repeat():
    engine = AlertEngine(AlertConfig(change_pct_threshold=3.0))
    assert len(engine.check(make_quote(change_pct=3.5))) == 1
    # 仍在阈值外，但已冷却，不重复告警
    assert engine.check(make_quote(change_pct=4.0)) == []
    # 回落到阈值内后冷却重置
    engine.check(make_quote(change_pct=0.5))
    assert len(engine.check(make_quote(change_pct=3.5))) == 1


def test_price_above_and_below():
    engine = AlertEngine(
        AlertConfig(price_above={"600519": 1680.0}, price_below={"600519": 1650.0})
    )
    alerts = engine.check(make_quote(price=1700.0, change_pct=0.5))
    assert [a.rule for a in alerts] == ["price_above"]

    alerts = engine.check(make_quote(price=1640.0, change_pct=-0.5))
    assert [a.rule for a in alerts] == ["price_below"]


def test_is_trading_time():
    sessions = [["09:30", "11:30"], ["13:00", "15:00"]]
    # 2026-08-17 是周一
    assert is_trading_time(sessions, datetime(2026, 8, 17, 10, 0))
    assert is_trading_time(sessions, datetime(2026, 8, 17, 14, 0))
    assert not is_trading_time(sessions, datetime(2026, 8, 17, 12, 0))  # 午休
    assert not is_trading_time(sessions, datetime(2026, 8, 17, 16, 0))  # 收盘后
    assert not is_trading_time(sessions, datetime(2026, 8, 15, 10, 0))  # 周六
