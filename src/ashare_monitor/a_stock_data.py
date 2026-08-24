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


# ── 融资融券（两融余额，日级）───────────────────────────────────

def margin_trading(code: str, page_size: int = 10) -> list[dict]:
    """融资融券明细：融资余额/买入/偿还 + 融券余额（东财 datacenter）。"""
    data = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX", filter_str=f'(SCODE="{code}")',
        page_size=page_size, sort_columns="DATE", sort_types="-1")
    rows = []
    for row in data:
        rows.append({
            "date": str(row.get("DATE", ""))[:10],
            "rzye": row.get("RZYE", 0),       # 融资余额(元)
            "rzmre": row.get("RZMRE", 0),     # 融资买入额
            "rqye": row.get("RQYE", 0),       # 融券余额(元)
            "rzrqye": row.get("RZRQYE", 0),   # 两融合计
        })
    return rows


# ── 大宗交易（溢价率 + 买卖方营业部）────────────────────────────

def block_trade(code: str, page_size: int = 20) -> list[dict]:
    """大宗交易记录：成交价/量 + 溢价率 + 买卖方（东财 datacenter）。"""
    data = eastmoney_datacenter(
        "RPT_DATA_BLOCKTRADE", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1")
    rows = []
    for row in data:
        close = row.get("CLOSE_PRICE") or 0
        deal_price = row.get("DEAL_PRICE") or 0
        premium = ((deal_price / close - 1) * 100) if close else 0
        rows.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "price": deal_price, "close": close,
            "premium_pct": round(premium, 2),
            "vol": row.get("DEAL_VOLUME", 0),
            "amount": row.get("DEAL_AMT", 0),
            "buyer": row.get("BUYER_NAME", ""),
            "seller": row.get("SELLER_NAME", ""),
        })
    return rows


# ── 个股资金流 120 日（主力/超大/大/中/小单）────────────────────

def stock_fund_flow_120d(code: str) -> list[dict]:
    """资金流日级（最近 120 交易日）：主力/超大/大/中/小单净流入（元）。"""
    market_code = 1 if code.startswith("6") else 0
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": f"{market_code}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": ("f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,"
                    "f61,f62,f63,f64,f65"),
        "lmt": "120",
    }
    headers = {"User-Agent": UA,
               "Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    try:
        d = em_get(url, params=params, headers=headers, timeout=15).json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("push2 资金流请求失败: %s", exc)
        return []
    klines = (d.get("data") or {}).get("klines") or []
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 7:
            rows.append({
                "date": parts[0],
                "main_net": _f(parts[1]) or 0,   # 主力净流入
                "small_net": _f(parts[2]) or 0,
                "mid_net": _f(parts[3]) or 0,
                "large_net": _f(parts[4]) or 0,
                "super_net": _f(parts[5]) or 0,  # 超大单
            })
    return rows


# ── 新浪财报三表（资产负债表/利润表/现金流量表）──────────────────

def sina_financial_report(code: str, report_type: str = "lrb",
                          num: int = 8) -> list[dict]:
    """新浪财报三表（fzb 资产负债 / lrb 利润 / llb 现金流）。

    结构：result.data.report_list 按报告期为键，每期 data 为行项列表
    （item_title / item_value / item_tongbi）。
    """
    prefix = "sh" if code.startswith("6") else "sz"
    url = ("https://quotes.sina.cn/cn/api/openapi.php/"
           "CompanyFinanceService.getFinanceReport2022")
    params = {"paperCode": f"{prefix}{code}", "source": report_type,
              "type": "0", "page": "1", "num": str(num)}
    r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=15)
    report_list = (r.json().get("result", {}).get("data", {})
                   .get("report_list", {})) or {}
    rows = []
    for period in sorted(report_list.keys(), reverse=True)[:num]:
        obj = report_list[period]
        rec = {"报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
        for it in obj.get("data", []) or []:
            title = it.get("item_title", "")
            if not title or it.get("item_value") is None:
                continue
            rec[title] = it.get("item_value")
            tongbi = it.get("item_tongbi")
            if tongbi not in (None, ""):
                rec[title + "_同比"] = tongbi
        rows.append(rec)
    return rows


# ── 巨潮公告全文检索（cninfo）───────────────────────────────────

def cninfo_announcements(code: str, page_size: int = 30) -> list[dict]:
    """巨潮公告检索：标题/类型/日期/详情页 URL（orgId 2026 新格式）。"""
    if code.startswith("6"):
        org_id = f"gssh0{code}"
    elif code.startswith("8") or code.startswith("4"):
        org_id = f"gsbj0{code}"
    else:
        org_id = f"gssz0{code}"
    url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    payload = {
        "stock": f"{code},{org_id}", "tabName": "fulltext",
        "pageSize": str(page_size), "pageNum": "1",
        "column": "", "category": "", "plate": "", "seDate": "",
        "searchkey": "", "secid": "", "sortName": "", "sortType": "",
        "isHLtitle": "true",
    }
    headers = {"User-Agent": UA,
               "Content-Type": "application/x-www-form-urlencoded",
               "Referer": "https://www.cninfo.com.cn/new/disclosure",
               "Origin": "https://www.cninfo.com.cn"}
    r = requests.post(url, data=payload, headers=headers, timeout=15)
    d = r.json()
    rows = []
    for item in d.get("announcements", []) or []:
        ts = item.get("announcementTime")
        date = (datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
                if isinstance(ts, (int, float)) else
                str(ts)[:10] if ts else "")
        rows.append({
            "title": item.get("announcementTitle", ""),
            "type": item.get("announcementTypeName", ""),
            "date": date,
            "url": ("https://www.cninfo.com.cn/new/disclosure/detail"
                    f"?annoId={item.get('announcementId', '')}"),
        })
    return rows


# ── 研报层：东财研报列表 + PDF 下载 ─────────────────────────────

REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"


def eastmoney_reports(code: str, max_pages: int = 3) -> list[dict]:
    """东财研报列表（含评级/预测 EPS）。"""
    import re

    all_records = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": "2000-01-01", "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        d = em_get(REPORT_API, params=params,
                   headers={"Referer": "https://data.eastmoney.com/"},
                   timeout=30).json()
        rows = d.get("data") or []
        if not rows:
            break
        all_records.extend(rows)
        if page >= (d.get("TotalPage", 1) or 1):
            break
    return all_records


def download_pdf(record: dict, target_dir: str = "output/reports") -> str | None:
    """下载单份研报 PDF（H3_{info_code}_1.pdf 模板），返回保存路径。"""
    import re
    from pathlib import Path

    info_code = record.get("infoCode", "")
    if not info_code:
        return None
    date = (record.get("publishDate") or "")[:10]
    org = record.get("orgSName") or "未知"
    title = re.sub(r'[\\/:*?"<>|]', "_", record.get("title", ""))[:80]
    target = Path(target_dir) / f"{date}_{org}_{title}.pdf"
    if target.exists():
        return str(target)
    r = em_get(PDF_TPL.format(info_code=info_code),
               headers={"Referer": "https://data.eastmoney.com/"}, timeout=60)
    if r.status_code == 200 and len(r.content) >= 1024:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(r.content)
        return str(target)
    return None


# ── 研报层：同花顺机构一致预期 EPS ─────────────────────────────

def ths_eps_forecast(code: str) -> list[dict]:
    """同花顺机构一致预期 EPS（basic.10jqka.com.cn HTML 表解析）。"""
    import io

    import pandas as pd

    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    r = requests.get(url,
                     headers={"User-Agent": UA,
                              "Referer": "https://basic.10jqka.com.cn/"},
                     timeout=15)
    r.encoding = "gbk"
    try:
        dfs = pd.read_html(io.StringIO(r.text))
    except ValueError:
        return []
    df = None
    for d in dfs:
        cols = [str(c) for c in d.columns]
        if any("每股收益" in c or "均值" in c for c in cols):
            df = d
            break
    if df is None:
        df = dfs[0] if dfs else None
    if df is None or df.empty:
        return []
    rows = []
    for _, row in df.iterrows():
        rec = {str(k): (str(v) if v is not None else "")
               for k, v in zip(df.columns, row)}
        rows.append(rec)
    return rows


# ── 美股富字段（腾讯批量：PE/市值，不封 IP） ────────────────

# 腾讯美股字段（实测校准）：3 现价 / 4 昨收 / 6 成交量 /
#   53 总市值(亿美元) / 65 PE(TTM)
_US_FIELD_PRICE, _US_FIELD_MCAP, _US_FIELD_PE = 3, 53, 65


def tencent_us_quote_batch(codes: list[str],
                           batch: int = 50) -> dict[str, dict]:
    """腾讯美股富字段批量查询（含 PE/市值，不封 IP）。

    返回 {code: {"name", "price", "pe_ttm", "mcap_yi", "change_pct"}}。
    字段索引 53 为亿美元市值（NVDA 50677 亿=5.07 万亿美元，实测校准）。
    """
    out: dict[str, dict] = {}
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        url = "https://qt.gtimg.cn/q=" + ",".join(
            c if c.upper().startswith("US") else f"us{c}" for c in chunk)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        r.encoding = "gbk"
        for line in r.text.split(";"):
            if "=" not in line:
                continue
            parts = line.split("~")
            if len(parts) <= _US_FIELD_PE:
                continue
            code = parts[2].split(".")[0]
            out[code] = {
                "name": parts[1],
                "price": _f(parts[_US_FIELD_PRICE]),
                "pe_ttm": _f(parts[_US_FIELD_PE]),
                "mcap_yi": _f(parts[_US_FIELD_MCAP]),
                "change_pct": _f(parts[32]) if len(parts) > 32 else None,
            }
    return out
