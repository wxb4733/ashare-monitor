"""A 股全栈数据工具包融合模块（源自 a-stock-data skill V3.2.3）。

融合来源：github.com/simonlin1212/a-stock-data（Simon 林，抖音「Simon林」，
公众号「硅基世纪」）——本模块提取其核心能力并适配 ashare-monitor 风格：
- em_get()：东财统一节流入口（串行限流 ≥1s + 随机抖动 + 会话复用）——防封
- tencent_quote_rich()：腾讯富字段行情（PE_TTM/PB/市值/换手率/涨跌停）——
  项目原 tencent provider 只解析价格，此处补全估值字段
- ths_hot_reason()：同花顺当日强势股 + 题材归因（reason tags，人工运营）
- dragon_tiger_board()：龙虎榜席位（买卖 TOP5 + 机构动向，东财 datacenter）
- lockup_expiry()：限售解禁日历（历史 + 未来 90 天，东财 datacenter）

数据源优先级（原 skill 铁律）：mootdx/腾讯不封 IP 优先，东财仅用独有数据
且必须走 em_get 节流。本模块未引入 mootdx（TCP 依赖可选装）。

免责声明：数据来自公开源，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

# ── 东财防封：全局节流 + 会话复用 ──────────────────────────────
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "Chrome/117.0.0.0 Safari/537.36")
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]


def em_get(url: str, params: dict | None = None, headers: dict | None = None,
           timeout: int = 15, **kwargs) -> requests.Response:
    """东财统一请求入口：自动节流 + 会话复用（防封铁律）。"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers,
                              timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                         filter_str: str = "", page_size: int = 50,
                         sort_columns: str = "", sort_types: str = "-1"
                         ) -> list[dict]:
    """东财数据中心统一查询（龙虎榜/解禁/融资融券等共用，内置限流）。"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ── 腾讯富字段行情（PE/PB/市值/换手率/涨跌停）────────────────────

def tencent_quote_rich(codes: list[str]) -> dict[str, dict]:
    """腾讯财经富字段行情（不封 IP）。

    字段索引速查（实测校准）：3 现价 / 4 昨收 / 31 涨跌额 / 32 涨跌幅 /
    37 成交额(万) / 38 换手率 / 39 PE(TTM) / 43 振幅（不是 PB！）/
    44 总市值(亿) / 46 PB / 47 涨停价 / 48 跌停价 / 49 量比 / 52 PE(静)
    """
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")
    resp = requests.get("https://qt.gtimg.cn/q=" + ",".join(prefixed),
                        headers={"User-Agent": UA}, timeout=10)
    resp.encoding = "gbk"
    result: dict[str, dict] = {}
    for line in resp.text.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name": vals[1],
            "price": _f(vals[3]), "last_close": _f(vals[4]),
            "open": _f(vals[5]),
            "change_pct": _f(vals[32]),
            "high": _f(vals[33]), "low": _f(vals[34]),
            "amount_wan": _f(vals[37]), "turnover_pct": _f(vals[38]),
            "pe_ttm": _f(vals[39]), "amplitude_pct": _f(vals[43]),
            "mcap_yi": _f(vals[44]), "float_mcap_yi": _f(vals[45]),
            "pb": _f(vals[46]),
            "limit_up": _f(vals[47]), "limit_down": _f(vals[48]),
            "vol_ratio": _f(vals[49]), "pe_static": _f(vals[52]),
        }
    return result


# ── 同花顺热点（当日强势股 + 题材归因）──────────────────────────

def ths_hot_reason(date: str | None = None) -> list[dict]:
    """同花顺当日强势股归因（reason tags 人工运营，实测 ~73ms 125 只）。"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    url = (f"http://zx.10jqka.com.cn/event/api/getharden/"
           f"date/{date}/orderby/date/orderway/desc/charset/GBK/")
    r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
    data = r.json()
    if data.get("errocode", 0) != 0:
        raise RuntimeError(f"同花顺热点错误: {data.get('errormsg', '')}")
    rows = data.get("data") or []
    out = []
    for row in rows:
        out.append({
            "code": row.get("code", ""), "name": row.get("name", ""),
            "reason": row.get("reason", ""),
            "change_pct": _f(row.get("zhangfu")),
            "close": _f(row.get("close")),
            "turnover_pct": _f(row.get("huanshou")),
            "amount": _f(row.get("chengjiaoe")),
        })
    out.sort(key=lambda x: x["change_pct"] or 0, reverse=True)
    return out


# ── 龙虎榜席位（买卖 TOP5 + 机构动向）───────────────────────────

def dragon_tiger_board(code: str, trade_date: str,
                       look_back: int = 30) -> dict:
    """龙虎榜聚合：上榜记录 + 买卖席位 TOP5 + 机构统计（东财 datacenter）。"""
    start = (datetime.strptime(trade_date, "%Y-%m-%d")
             - timedelta(days=look_back)).strftime("%Y-%m-%d")
    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=(f"(TRADE_DATE>='{start}')(TRADE_DATE<='{trade_date}')"
                    f"(SECURITY_CODE=\"{code}\")"),
        page_size=50, sort_columns="TRADE_DATE", sort_types="-1")
    for row in data:
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
        })
    seats = {"buy": [], "sell": []}
    institution = {"buy_wan": 0, "sell_wan": 0, "net_wan": 0}
    if records:
        latest = records[0]["date"]
        buy_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=f"(TRADE_DATE='{latest}')(SECURITY_CODE=\"{code}\")",
            page_size=10, sort_columns="BUY", sort_types="-1")
        sell_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSSELL",
            filter_str=f"(TRADE_DATE='{latest}')(SECURITY_CODE=\"{code}\")",
            page_size=10, sort_columns="SELL", sort_types="-1")
        for row in buy_data[:5]:
            seats["buy"].append(_seat(row))
        for row in sell_data[:5]:
            seats["sell"].append(_seat(row))
        for row in buy_data:
            if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                institution["buy_wan"] += (row.get("BUY") or 0) / 10000
        for row in sell_data:
            if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                institution["sell_wan"] += (row.get("SELL") or 0) / 10000
        institution["buy_wan"] = round(institution["buy_wan"], 1)
        institution["sell_wan"] = round(institution["sell_wan"], 1)
        institution["net_wan"] = round(institution["buy_wan"]
                                       - institution["sell_wan"], 1)
    return {"records": records, "seats": seats, "institution": institution}


def _seat(row: dict) -> dict:
    return {
        "name": row.get("OPERATEDEPT_NAME", ""),
        "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
        "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
        "net_wan": round((row.get("NET") or 0) / 10000, 1),
    }


# ── 限售解禁日历（历史 + 未来 90 天）────────────────────────────

def lockup_expiry(code: str, trade_date: str | None = None,
                  forward_days: int = 90) -> dict:
    """解禁日历：历史解禁 + 未来 forward_days 天待解禁（东财 datacenter）。"""
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    history = []
    hist_data = eastmoney_datacenter(
        "RPT_LIFT_STAGE", filter_str=f"(SECURITY_CODE=\"{code}\")",
        page_size=15, sort_columns="FREE_DATE", sort_types="-1")
    for row in hist_data:
        history.append({
            "date": str(row.get("FREE_DATE", ""))[:10],
            "type": row.get("LIMITED_STOCK_TYPE", ""),
            "shares": row.get("FREE_SHARES_NUM", 0),
            "ratio_pct": row.get("FREE_RATIO", 0),
        })
    end = (datetime.strptime(trade_date, "%Y-%m-%d")
           + timedelta(days=forward_days)).strftime("%Y-%m-%d")
    upcoming = []
    up_data = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=(f"(SECURITY_CODE=\"{code}\")"
                    f"(FREE_DATE>='{trade_date}')(FREE_DATE<='{end}')"),
        page_size=20, sort_columns="FREE_DATE", sort_types="1")
    for row in up_data:
        upcoming.append({
            "date": str(row.get("FREE_DATE", ""))[:10],
            "type": row.get("LIMITED_STOCK_TYPE", ""),
            "shares": row.get("FREE_SHARES_NUM", 0),
            "ratio_pct": row.get("FREE_RATIO", 0),
        })
    return {"history": history, "upcoming": upcoming}


def _f(v) -> float | None:
    try:
        if v in (None, "", "--"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
