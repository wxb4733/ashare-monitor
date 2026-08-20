"""持仓管理与盈亏日报单元测试。"""

import pytest

from ashare_monitor.position import (
    Position,
    build_position_report,
    currency_hint,
    fill_prices,
    load_positions,
)


class _Cfg:
    def __init__(self, positions):
        self.positions = positions
        self.obsidian = type("O", (), {"vault": ""})()


def test_load_positions():
    cfg = _Cfg([
        {"code": "002594", "market": "ashare", "name": "比亚迪", "cost": 50.0,
         "shares": 1000},
        {"code": "01211", "market": "hk", "cost": 40.0, "shares": 500},
    ])
    ps = load_positions(cfg)
    assert len(ps) == 2
    assert ps[0].code == "002594" and ps[0].cost == 50.0
    assert ps[0].cost_value == 50000.0
    assert ps[1].market == "hk"


def test_position_properties():
    p = Position(code="002594", name="比亚迪", market="ashare",
                 cost=50.0, shares=1000, price=60.0)
    assert p.market_value == 60000.0
    assert p.pnl == 10000.0
    assert p.pnl_pct == pytest.approx(20.0)
    # 无现价
    p2 = Position(code="600000", name="浦发", market="ashare",
                  cost=10.0, shares=100)
    assert p2.pnl is None and p2.pnl_pct is None


def test_fill_prices_from_db(tmp_path, monkeypatch):
    from ashare_monitor.storage import record_klines

    db = str(tmp_path / "pos.db")
    monkeypatch.setattr("ashare_monitor.storage.load_klines",
                        lambda code, market, db_path=None: [
                            {"date": "2026-08-20", "open": 55.0, "close": 55.5,
                             "high": 56.0, "low": 54.5, "volume": 1000.0},
                        ])
    p = Position(code="002594", name="比亚迪", market="ashare",
                 cost=50.0, shares=1000)
    fill_prices([p])
    assert p.price == 55.5
    assert p.pnl == pytest.approx(5500.0)


def test_build_position_report():
    ps = [
        Position(code="002594", name="比亚迪", market="ashare",
                 cost=50.0, shares=1000, price=60.0),
        Position(code="01211", name="比亚迪股份", market="hk",
                 cost=40.0, shares=500, price=38.0),
    ]
    html, md = build_position_report(ps, as_of="2026-08-20")
    assert "持仓盈亏日报" in html
    assert "比亚迪(002594)" in html and "比亚迪股份(01211)" in html
    assert "+10000.00" in html and "-1000.00" in html
    assert "合计" in html and "人民币" in html or "混合" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 持仓盈亏 2026-08-20")


def test_currency_hint():
    hk = [Position(code="01211", name="x", market="hk", cost=1.0, shares=1)]
    a = [Position(code="600000", name="x", market="ashare", cost=1.0, shares=1)]
    both = hk + a
    assert currency_hint(hk) == "港元"
    assert currency_hint(a) == "人民币"
    assert currency_hint(both) == "混合"
