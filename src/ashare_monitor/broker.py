"""模拟经纪人（backtrader Broker 模式的轻量版）。

核心升级（相对原一次性撮合函数）：
    1. 现金账户：买入扣款（含佣金）、卖出入账（扣佣金+印花税）
    2. 订单状态机：New → Filled / Rejected（可扩展 Canceled/Partial）
    3. 佣金模型：commission_bps 佣金（双向）+ stamp_duty_bps 印花税（卖出）
       ——默认 0（与历史行为零变化），开启请传真实费率：
       A 股参考：佣金万 2.5（2.5bp）+ 印花税 0.05%（卖出 5bp）
    4. 净资产（equity）= 现金 + 持仓市值——资金曲线的计算基础

持久化（storage）：
    paper_account  （单行 id=1：cash 现金余额）
    paper_positions（持仓，复用原表）
    paper_orders   （订单状态机全生命周期：New/Filled/Rejected）

用法：
    broker = PaperBroker.load()
    broker.place_order("600519", "贵州茅台", "buy", 100, 1450.0)
    result = broker.process_orders()      # 即时市价撮合 → Filled/Rejected
    broker.save()
    broker.equity(prices)                 # 净资产
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

ORDER_STATUS = ("New", "Filled", "Rejected", "Canceled")


class PaperBroker:
    """模拟经纪人：现金 + 持仓 + 订单状态机。"""

    def __init__(self, cash: float = 0.0,
                 commission_bps: float = 0.0,
                 stamp_duty_bps: float = 0.0):
        self.cash = cash
        self.commission_bps = commission_bps     # 佣金（单边，万分比）
        self.stamp_duty_bps = stamp_duty_bps     # 印花税（卖出，万分比）
        self.positions: dict[str, dict] = {}
        self.orders: list[dict] = []
        self._order_seq = 0

    # ── 订单状态机 ──────────────────────────────────────────

    def place_order(self, code: str, name: str, side: str, shares: int,
                    price: float, reason: str = "") -> dict:
        """创建订单（状态 New）。"""
        self._order_seq += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        order = {
            "id": self._order_seq, "code": code, "name": name,
            "side": side, "shares": shares, "price": round(price, 2),
            "fee": 0.0, "status": "New", "reason": reason,
            "created": now, "updated": now,
        }
        self.orders.append(order)
        return order

    def process_orders(self) -> list[dict]:
        """撮合全部 New 订单（即时市价）→ Filled / Rejected。"""
        changed = []
        for o in self.orders:
            if o["status"] != "New":
                continue
            new_status = self._try_fill(o)
            o["status"] = new_status
            o["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            changed.append(o)
        return changed

    def cancel_order(self, order_id: int) -> bool:
        """撤销 New 状态订单（已撮合的不可撤销）。"""
        for o in self.orders:
            if o["id"] == order_id and o["status"] == "New":
                o["status"] = "Canceled"
                o["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return True
        return False

    def _try_fill(self, o: dict) -> str:
        price = o["price"]
        if price <= 0 or o["shares"] <= 0:
            return "Rejected"
        if o["side"] == "buy":
            fee = o["shares"] * price * self.commission_bps / 10000
            cost = o["shares"] * price + fee
            if cost > self.cash + 1e-6:
                return "Rejected"          # 资金不足
            self.cash -= cost
            self._update_position(o["code"], o["name"], o["shares"], price)
            o["fee"] = round(fee, 2)
            return "Filled"
        # sell
        pos = self.positions.get(o["code"])
        if not pos or pos["shares"] < o["shares"]:
            return "Rejected"              # 持仓不足
        fee = (o["shares"] * price
               * (self.commission_bps + self.stamp_duty_bps) / 10000)
        self.cash += o["shares"] * price - fee
        self._reduce_position(o["code"], o["shares"])
        o["fee"] = round(fee, 2)
        return "Filled"

    def _update_position(self, code: str, name: str, shares: int,
                         price: float) -> None:
        pos = self.positions.get(code)
        if not pos:
            self.positions[code] = {"code": code, "name": name,
                                    "shares": shares, "avg_cost": price}
        else:
            total = pos["shares"] * pos["avg_cost"] + shares * price
            pos["shares"] += shares
            pos["avg_cost"] = total / pos["shares"]

    def _reduce_position(self, code: str, shares: int) -> None:
        pos = self.positions.get(code)
        if not pos:
            return
        pos["shares"] -= shares
        if pos["shares"] <= 0:
            del self.positions[code]

    # ── 账户视图 ────────────────────────────────────────────

    def equity(self, prices: dict[str, float] | None = None) -> float:
        """净资产 = 现金 + 持仓市值（无现价时用成本价近似）。"""
        prices = prices or {}
        mv = 0.0
        for code, pos in self.positions.items():
            p = prices.get(code)
            mv += pos["shares"] * (p if p else pos["avg_cost"])
        return self.cash + mv

    def positions_list(self) -> list[dict]:
        return list(self.positions.values())

    def filled_orders(self) -> list[dict]:
        return [o for o in self.orders if o["status"] == "Filled"]

    def pending_orders(self) -> list[dict]:
        return [o for o in self.orders if o["status"] == "New"]

    # ── 持久化 ──────────────────────────────────────────────

    def save(self, conn=None) -> None:
        """落库：paper_account / paper_positions / paper_orders。"""
        import sqlite3

        from .storage import get_conn

        own = conn is None
        conn = conn or get_conn()
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS paper_account "
                    "(id INTEGER PRIMARY KEY, cash REAL)")
                conn.execute(
                    "INSERT OR REPLACE INTO paper_account (id, cash) "
                    "VALUES (1, ?)", (round(self.cash, 2),))
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS paper_orders ("
                    "id INTEGER PRIMARY KEY, code TEXT, name TEXT, side TEXT, "
                    "shares INTEGER, price REAL, fee REAL, status TEXT, "
                    "reason TEXT, created TEXT, updated TEXT)")
                for o in self.orders:
                    conn.execute(
                        "INSERT OR REPLACE INTO paper_orders "
                        "(id, code, name, side, shares, price, fee, status, "
                        "reason, created, updated) VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?)",
                        (o["id"], o["code"], o["name"], o["side"],
                         o["shares"], o["price"], o["fee"], o["status"],
                         o["reason"], o["created"], o["updated"]))
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS paper_positions ("
                    "code TEXT PRIMARY KEY, name TEXT, shares INTEGER, "
                    "avg_cost REAL, updated TEXT)")
                conn.execute("DELETE FROM paper_positions")
                for pos in self.positions.values():
                    conn.execute(
                        "INSERT OR REPLACE INTO paper_positions "
                        "(code, name, shares, avg_cost, updated) "
                        "VALUES (?,?,?,?,?)",
                        (pos["code"], pos["name"], pos["shares"],
                         pos["avg_cost"],
                         datetime.now().strftime("%Y-%m-%d")))
        finally:
            if own:
                conn.close()

    @classmethod
    def load(cls, conn=None) -> "PaperBroker":
        """从库恢复账户（无记录时现金 0、空仓）。"""
        import sqlite3

        from .storage import get_conn

        own = conn is None
        conn = conn or get_conn()
        conn.row_factory = sqlite3.Row
        broker = cls()
        try:
            try:
                row = conn.execute(
                    "SELECT cash FROM paper_account WHERE id=1").fetchone()
            except sqlite3.OperationalError:
                row = None
            if row:
                broker.cash = float(row["cash"])
            try:
                rows = conn.execute(
                    "SELECT * FROM paper_positions ORDER BY code").fetchall()
            except sqlite3.OperationalError:
                rows = []
            for r in rows:
                broker.positions[r["code"]] = {
                    "code": r["code"], "name": r["name"],
                    "shares": r["shares"], "avg_cost": r["avg_cost"]}
            try:
                orders = conn.execute(
                    "SELECT * FROM paper_orders ORDER BY id").fetchall()
            except sqlite3.OperationalError:
                orders = []
            for r in orders:
                o = dict(r)
                broker.orders.append(o)
                broker._order_seq = max(broker._order_seq, o["id"])
        finally:
            if own:
                conn.close()
        return broker
