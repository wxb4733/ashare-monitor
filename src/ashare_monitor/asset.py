"""资产画像统一接口（AssetProfile）——跨领域（股票/数字货币）通用。

设计：把"基本面"抽象为五个领域无关维度，领域差异由各 market 的实现隔离：
- market_cap   市值（元/USDT）
- supply_total 总供给（股票=总股本，币=总发行量）
- growth_rate  增长（股票=净利同比%，币=供给增速/通胀率%）
- yield_rate   收益（股票=股息率%，币=质押/利息收益率%）
- valuation    估值（股票=PE/PB，币=NVT/市值-交易量比等，dict 保留领域字段）

股票实现（stock_profile）：聚合 fundamentals(ROE/增速) + valuation(PE/PB) + quotes(现价)。
数字货币实现：Phase 2 接入（CoinGecko 代币经济 + 链上数据），当前占位返回 WARN 状态。

声明：数据来自公开源，不构成投资建议。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AssetProfile:
    code: str
    name: str
    market: str
    market_cap: float | None = None     # 市值（元 / USDT）
    supply_total: float | None = None   # 总供给（股 / 币）
    growth_rate: float | None = None    # 增长 %（净利同比 / 供给增速）
    yield_rate: float | None = None     # 收益 %（股息率 / 质押收益率）
    valuation: dict = field(default_factory=dict)   # 估值键值（PE/PB/NVT…）
    extra: dict = field(default_factory=dict)       # 领域特有字段（ROE/净利率…）
    status: str = "OK"                  # OK / WARN / MISSING
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "market": self.market,
            "market_cap": self.market_cap, "supply_total": self.supply_total,
            "growth_rate": self.growth_rate, "yield_rate": self.yield_rate,
            "valuation": self.valuation, "extra": self.extra,
            "status": self.status, "note": self.note,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", "", "none"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def stock_profile(code: str, name: str = "", market: str = "ashare",
                  cfg=None) -> AssetProfile:
    """股票画像：聚合财报(ROE/增速) + 估值(PE/PB) + 现价/市值。"""
    p = AssetProfile(code=code, name=name, market=market)
    try:
        from .fundamentals import fetch_financials

        fins = fetch_financials(code, periods=2, market=market)
        if fins and fins[0].roe is not None:
            f0 = fins[0]
            p.growth_rate = f0.profit_yoy
            p.extra["roe"] = f0.roe
            p.extra["report_date"] = f0.report_date
            if f0.gross_margin is not None:
                p.extra["gross_margin"] = f0.gross_margin
            if f0.net_margin is not None:
                p.extra["net_margin"] = f0.net_margin
        else:
            p.status = "WARN"
            p.note = "财报字段缺失"
    except Exception as exc:  # noqa: BLE001
        p.status = "WARN"
        p.note = f"财报获取失败：{str(exc)[:40]}"

    try:
        from .valuation import fetch_valuation

        v = fetch_valuation(code, years=5)
        if v is not None and v.pe_ttm is not None:
            p.valuation = {"pe_ttm": v.pe_ttm, "pe_pct": v.pe_pct,
                           "pb_mrq": v.pb_mrq, "pb_pct": v.pb_pct}
            p.extra["close"] = v.close
        else:
            p.status = "WARN"
            p.note = "估值数据缺失"
    except Exception as exc:  # noqa: BLE001
        p.status = "WARN"
        p.note = f"估值获取失败：{str(exc)[:40]}"

    try:
        from .quotes import fetch_spot_quotes

        qs, _ = fetch_spot_quotes([code], market=market)
        if qs:
            q = qs[0]
            p.extra["price"] = q.price
            p.market_cap = getattr(q, "market_cap", None)
            p.extra["change_pct"] = getattr(q, "change_pct", None)
    except Exception:  # noqa: BLE001
        pass

    # 股息率（年度派息 / 现价）
    try:
        from .dividend import load_dividend_history

        rows = load_dividend_history(code)
        paid = [r for r in rows if r.yield_pct is not None]
        if paid:
            p.yield_rate = paid[-1].yield_pct
    except Exception:  # noqa: BLE001
        pass

    if market != "ashare":
        p.status = "WARN"
        p.note = "港股部分字段受限（如实）"
    return p


def crypto_profile(code: str, name: str = "") -> AssetProfile:
    """数字货币画像（Phase 2 实现占位，返回 WARN）。"""
    return AssetProfile(
        code=code, name=name, market="crypto",
        status="WARN",
        note="crypto 画像待 Phase 2 接入（CoinGecko 代币经济 + 链上数据）",
    )


def build_profile(code: str, name: str = "", market: str = "ashare",
                  cfg=None) -> AssetProfile:
    """按市场分发画像实现（通用入口）。"""
    if market == "crypto":
        return crypto_profile(code, name)
    return stock_profile(code, name, market, cfg)
