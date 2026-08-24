"""PaperBroker（backtrader 模式模拟经纪人）单元测试。"""

import pytest


def test_order_state_machine_buy():
    """买入订单：New → Filled（资金充足）/ Rejected（资金不足）。"""
    from ashare_monitor.broker import PaperBroker

    b = PaperBroker(cash=100_000.0)
    o1 = b.place_order("600900", "长江电力", "buy", 100, 28.5, reason="新进")
    o2 = b.place_order("600519", "贵州茅台", "buy", 100, 1450.0, reason="新进")
    assert o1["status"] == "New" and o2["status"] == "New"
    changed = b.process_orders()
    assert len(changed) == 2
    by_id = {o["id"]: o for o in changed}
    assert by_id[o1["id"]]["status"] == "Filled"
    assert by_id[o2["id"]]["status"] == "Rejected"   # 14.5 万 > 现金
    # 现金：10 万 - 2850 = 97150
    assert b.cash == pytest.approx(97_150.0)
    assert b.positions["600900"]["shares"] == 100
    assert b.positions["600900"]["avg_cost"] == pytest.approx(28.5)


def test_order_sell_and_reduce():
    """卖出：现金入账 + 持仓减少/清仓；持仓不足拒单。"""
    from ashare_monitor.broker import PaperBroker

    b = PaperBroker(cash=100_000.0)
    b.place_order("000001", "平安银行", "buy", 1000, 11.0)
    b.process_orders()
    b.place_order("000001", "平安银行", "sell", 400, 12.0)
    b.place_order("000001", "平安银行", "sell", 1000, 12.0)   # 超持仓
    changed = b.process_orders()
    status = {o["shares"]: o["status"] for o in changed}
    assert status[400] == "Filled"
    assert status[1000] == "Rejected"
    assert b.positions["000001"]["shares"] == 600
    # 现金：10 万 - 买 11000 + 卖 4800 = 93800（无佣金）
    assert b.cash == pytest.approx(93_800.0)
    # 清仓：再卖 600
    b.place_order("000001", "平安银行", "sell", 600, 12.0)
    b.process_orders()
    assert "000001" not in b.positions


def test_commission_and_stamp():
    """佣金（双向）+ 印花税（卖出）：现金计算。"""
    from ashare_monitor.broker import PaperBroker

    b = PaperBroker(cash=100_000.0, commission_bps=2.5, stamp_duty_bps=5.0)
    b.place_order("600900", "长江电力", "buy", 1000, 28.5)
    b.process_orders()
    # 买 1000×28.5=28500 + 佣金 28500×2.5/1e4=7.125 → 现金 100000-28507.125
    assert b.cash == pytest.approx(100_000 - 28_507.125)
    # 卖 500×30=15000 - 佣金 15000×2.5/1e4=3.75 - 印花税 15000×5/1e4=7.5
    b.place_order("600900", "长江电力", "sell", 500, 30.0)
    changed = b.process_orders()
    sell_order = [o for o in changed if o["side"] == "sell"][0]
    assert sell_order["fee"] == pytest.approx(11.25)   # 3.75+7.5
    assert b.cash == pytest.approx(100_000 - 28_507.125 + 15_000 - 11.25)


def test_avg_cost_weighted():
    """加仓后 avg_cost 加权平均。"""
    from ashare_monitor.broker import PaperBroker

    b = PaperBroker(cash=1_000_000.0)
    b.place_order("600900", "长江电力", "buy", 100, 28.0)
    b.place_order("600900", "长江电力", "buy", 100, 32.0)
    b.process_orders()
    assert b.positions["600900"]["avg_cost"] == pytest.approx(30.0)


def test_equity():
    """净资产 = 现金 + 持仓市值（无现价按成本）。"""
    from ashare_monitor.broker import PaperBroker

    b = PaperBroker(cash=50_000.0)
    b.place_order("000001", "平安银行", "buy", 1000, 10.0)
    b.process_orders()
    assert b.equity() == pytest.approx(50_000.0)          # 现金4万+持仓1万
    assert b.equity({"000001": 12.0}) == pytest.approx(52_000.0)  # 按现价


def test_cancel_order():
    """撤销 New 订单；已成交不可撤销。"""
    from ashare_monitor.broker import PaperBroker

    b = PaperBroker(cash=100_000.0)
    o1 = b.place_order("600900", "长江电力", "buy", 100, 28.5)
    b.process_orders()                      # o1 成交
    o2 = b.place_order("600900", "长江电力", "buy", 100, 28.5)  # 保持 New
    assert b.cancel_order(o1["id"]) is False   # 已成交不可撤
    assert b.cancel_order(o2["id"]) is True    # New 可撤
    assert o2["status"] == "Canceled"
    assert len(b.filled_orders()) == 1


def test_save_load_roundtrip(tmp_path, monkeypatch):
    """save/load 往返：现金/持仓/订单状态机完整恢复。"""
    from ashare_monitor.broker import PaperBroker
    from ashare_monitor.storage import get_conn

    db = str(tmp_path / "broker.db")
    orig = get_conn

    import ashare_monitor.storage as storage
    monkeypatch.setattr(storage, "get_conn",
                        lambda: orig(db_path=db))

    b = PaperBroker(cash=88_000.0, commission_bps=2.5)
    b.place_order("600900", "长江电力", "buy", 100, 28.5)
    b.place_order("600900", "长江电力", "buy", 50, 29.0)   # 现金不足? 2850+1450=4300<88000 ok
    b.process_orders()
    b.save()

    b2 = PaperBroker.load()
    assert b2.cash == pytest.approx(88_000.0 - 4_300.0 - 4_300 * 2.5 / 1e4)
    assert b2.positions["600900"]["shares"] == 150
    assert b2.positions["600900"]["avg_cost"] == pytest.approx(
        (100 * 28.5 + 50 * 29.0) / 150)
    assert len(b2.filled_orders()) == 2
    assert all(o["status"] == "Filled" for o in b2.orders)


def test_execute_paper_trade_commission(tmp_path, monkeypatch):
    """execute_paper_trade 带佣金：现金扣款含佣金。"""
    from ashare_monitor import strategy

    db = str(tmp_path / "pt.db")
    from ashare_monitor.storage import get_conn as orig
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig(db_path=db))

    class _Q:
        code = "600900"
        price = 28.5

    monkeypatch.setattr(
        "ashare_monitor.quotes.fetch_spot_quotes",
        lambda codes, market="ashare": ([_Q()], "tencent"))
    targets = [strategy.TargetPosition("600900", "长江电力", 100.0, 100_000.0)]
    result = strategy.execute_paper_trade(
        targets, cash=100_000.0, commission_bps=2.5)
    # 3500 股 × 28.5 = 99750 + 佣金 24.94 → 现金 100000 - 99750 - 24.94
    assert result["fills"][0]["shares"] == 3500
    assert result["fills"][0]["fee"] == pytest.approx(24.94, abs=0.1)
    assert result["cash"] == pytest.approx(100_000 - 99_750 - 24.94, abs=0.1)
