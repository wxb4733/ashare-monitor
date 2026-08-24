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
    """数字货币画像（CoinGecko 代币经济映射到五维）。

    :param code: CoinGecko 币 id（如 bitcoin / ethereum）；可传 Binance 交易对
                 （如 BTCUSDT）自动映射小写基础币。
    映射：market_cap / supply_total(总量) / growth_rate(供给增速:流通占比近似) /
          yield_rate(质押收益：CoinGecko 基础接口无，标 None 如实) /
          valuation(NVT 近似 = 市值/24h 交易量)。
    注意：CoinGecko 境外 API 在部分沙箱网络不可达（已知），本机直连通常可用。
    """
    import requests

    cid = code.lower()
    if cid.endswith("usdt"):
        cid = cid[:-4]
    p = AssetProfile(code=code, name=name or cid.upper(), market="crypto")
    try:
        d = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "ids": cid,
                    "order": "market_cap_desc", "per_page": 1, "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "24h"},
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=15,
        ).json()
        if not isinstance(d, list) or not d:
            raise RuntimeError(f"CoinGecko 无 {cid} 数据")
        c = d[0]
        p.extra["price"] = c.get("current_price")
        p.extra["symbol"] = c.get("symbol")
        p.market_cap = c.get("market_cap")
        p.supply_total = c.get("total_supply")
        circ = c.get("circulating_supply")
        p.extra["circulating_supply"] = circ
        p.extra["volume_24h"] = c.get("total_volume")
        p.extra["change_24h_pct"] = c.get("price_change_percentage_24h")
        # 增长维：流通/总量比例（近似供给释放进度；通胀率需链上数据，如实 None）
        if circ and p.supply_total:
            p.growth_rate = circ / p.supply_total * 100
            p.extra["circulation_pct"] = round(p.growth_rate, 2)
        # 估值维：NVT 近似（市值/24h 交易量）
        vol = c.get("total_volume")
        if p.market_cap and vol:
            p.valuation["nvt_approx"] = round(p.market_cap / vol, 2)
        p.valuation["ath"] = c.get("ath")
        p.valuation["ath_change_pct"] = c.get("ath_change_percentage")
        p.note = ("质押收益率/通胀率需链上数据（fetch_onchain_profile 占位，"
                  "Phase 3 接入）；增长维=流通/总量比例")
    except Exception as exc:  # noqa: BLE001
        p.status = "WARN"
        p.note = f"CoinGecko 获取失败：{str(exc)[:60]}（境外 API 沙箱可能不可达，本机直连通常可用）"
    return p


def us_profile(code: str, name: str = "") -> AssetProfile:
    """美股画像（东财美股财务指标：ROE/毛利率/净利增速/EPS）。"""
    import akshare as ak

    p = AssetProfile(code=code, name=name, market="us")
    try:
        df = ak.stock_financial_us_analysis_indicator_em(
            symbol=code, indicator="年报")
        if df is None or df.empty:
            raise RuntimeError("美股财务无数据")
        # 按报告期降序，取最新有 ROE 的行
        df = df.copy()
        if "REPORT_DATE" in df.columns:
            df = df.sort_values("REPORT_DATE", ascending=False)
        r = None
        for _, row in df.iterrows():
            if _f(row.get("ROE_AVG")) is not None:
                r = row
                break
        if r is None:
            r = df.iloc[0]
        p.growth_rate = _f(r.get("PARENT_HOLDER_NETPROFIT_YOY"))
        p.extra["roe"] = _f(r.get("ROE_AVG"))
        p.extra["gross_margin"] = _f(r.get("GROSS_PROFIT_RATIO"))
        p.extra["eps"] = _f(r.get("BASIC_EPS"))
        p.extra["report_date"] = str(r.get("REPORT_DATE"))[:10]
        p.extra["revenue"] = _f(r.get("OPERATE_INCOME"))
        p.extra["net_profit"] = _f(r.get("PARENT_HOLDER_NETPROFIT"))
        p.note = "东财美股财务（年报口径）"
    except Exception as exc:  # noqa: BLE001
        p.status = "WARN"
        p.note = f"美股财务获取失败：{str(exc)[:50]}"
    return p


def build_profile(code: str, name: str = "", market: str = "ashare",
                  cfg=None) -> AssetProfile:
    """按市场分发画像实现（通用入口）。"""
    if market == "crypto":
        return crypto_profile(code, name)
    if market == "us":
        return us_profile(code, name)
    return stock_profile(code, name, market, cfg)


# ===================== 链上数据占位（Phase 3 预留） =====================

# 币质押收益率/通胀率需链上数据。免费源探测记录（如实）：
# - CryptoCompare blockchain/latest：沙箱不可达且接口覆盖有限（无质押数据）
# - beaconcha.in（ETH 质押率）：境外 API，沙箱不可达
# - 链上 RPC（eth 供应量等）：需节点或公共 RPC，未接入
# 结论：质押收益/通胀率暂无免费可靠源，字段保持 None（不硬凑）。
# 本机可用源（待验证）：Lido/DefiLlama 质押数据、公共 RPC。


def fetch_onchain_profile(code: str) -> dict:
    """链上画像（Phase 3 真实实现）：通胀率 + 质押收益。

    免费源（沙箱境外 API 不可达 → mock 测试 + 本机验证）：
    - BTC 通胀率：blockchain.info charts（无 key，年新增供给/总量）
    - ETH 质押收益：Lido stETH APR（无 key，近似全网质押收益率）

    返回：{"staking_yield_pct": ..., "inflation_pct": ...,
           "note": 数据源说明}；获取失败时字段 None + WARN 说明（如实）。
    """
    import requests

    code = code.upper()
    result = {"staking_yield_pct": None, "inflation_pct": None, "note": ""}
    try:
        if "BTC" in code:
            d = requests.get(
                "https://api.blockchain.info/charts/total-bitcoins",
                params={"timespan": "1year", "format": "json"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=15).json()
            vals = [v["y"] for v in (d.get("values") or [])]
            if len(vals) >= 2 and vals[-1]:
                inflation = (vals[-1] - vals[0]) / vals[-1] * 100
                result["inflation_pct"] = round(inflation, 4)
                result["note"] = ("BTC 通胀率=近 1 年新增供给/总量"
                                  "（blockchain.info，无 key）")
        elif "ETH" in code:
            d = requests.get("https://api.lido.fi/v1/steth/apr/latest",
                             headers={"User-Agent": "Mozilla/5.0"},
                             timeout=15).json()
            apr = (d.get("data") or {}).get("apr") if isinstance(d, dict)                 else None
            if apr is not None:
                result["staking_yield_pct"] = round(float(apr) * 100, 2)
                result["note"] = ("ETH 质押收益≈stETH APR（Lido，无 key，"
                                  "近似全网质押率）")
        if not result["note"]:
            raise RuntimeError(f"未识别的链上标的 {code}")
    except Exception as exc:  # noqa: BLE001
        result["note"] = (f"链上数据获取失败：{str(exc)[:60]}"
                          "（境外 API 沙箱可能不可达，本机直连通常可用）")
    return result
