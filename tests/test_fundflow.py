"""资金面监控单元测试（mock 网络）。"""

import pytest

from ashare_monitor.fundflow import (
    FundFlow,
    build_fundflow_report,
    fetch_fundflow,
)


def test_fetch_fundflow(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"klines": [
                "2026-08-20,491193312.0,-168086928.0,-323106384.0,76863808.0,414329504.0",
            ]}}

    monkeypatch.setattr("ashare_monitor.fundflow.requests.get",
                        lambda *a, **k: _Resp())
    f = fetch_fundflow("002594", "ashare", "比亚迪")
    assert f.code == "002594" and f.date == "2026-08-20"
    assert f.main_net == pytest.approx(4.91)      # 491193312 元 → 4.91 亿
    assert f.xl_net == pytest.approx(4.14)        # 超大单 414329504 → 4.14 亿
    assert f.l_net == pytest.approx(0.77)         # 大单 76863808 → 0.77 亿
    assert f.s_net == pytest.approx(-1.68)        # 小单
    assert f.m_net == pytest.approx(-3.23)        # 中单


def test_fetch_fundflow_hk_no_data():
    f = fetch_fundflow("01211", "hk", "比亚迪股份")
    assert f.main_net is None and f.market == "hk"


def test_build_fundflow_report():
    flows = [
        FundFlow("002594", "比亚迪", "ashare", "2026-08-20",
                 main_net=4.91, xl_net=4.14, l_net=0.77, m_net=-3.23, s_net=-1.68),
    ]
    hsgt = [
        {"date": "2026-08-20", "board": "港股通(沪)", "direction": "南向",
         "net_buy": -51.11, "up": 425, "down": 182, "index_chg": 0.8},
        {"date": "2026-08-20", "board": "沪股通", "direction": "北向",
         "net_buy": 0.0, "up": 1141, "down": 464, "index_chg": 0.24},
    ]
    html, md = build_fundflow_report(flows, hsgt, as_of="2026-08-21")
    assert "资金面监控" in html
    assert "主力净流入" in html and "+4.91 亿" in html
    assert "港股通(沪)" in html and "北向" in html
    assert "停止披露" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 资金面监控")
