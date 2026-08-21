"""历史数据回填：自上市以来的全量行情 / 公告 / 研报 / 财报。

- backfill_kline：日 K 全量入库（A 股 akshare stock_zh_a_hist；港股 akshare stock_hk_hist）
- backfill_news：公告/研报多页拉取入库（东财接口分页/按年）
- backfill_financial：财报全量页入库（东财业绩报表分页）

入库到 data/ashare_monitor.db（klines / announcements / research_reports / financials 表）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .storage import (
    record_announcements,
    record_financials,
    record_klines,
    record_research_reports,
)

logger = logging.getLogger(__name__)

# 已知上市日（用于 K 线回填起点，其他标的走全量兜底）
KNOWN_IPO_DATES = {
    ("ashare", "002594"): "2011-06-30",
    ("hk", "01211"): "2002-07-31",
    ("hk", "01810"): "2018-07-09",   # 小米集团
}


def _start_date(code: str, market: str) -> str:
    return KNOWN_IPO_DATES.get((market, code), "19900101")


def backfill_kline(code: str, market: str) -> tuple[int, int]:
    """回填日 K 全量（akshare 优先，腾讯 K 线按日期窗口分段降级）。

    :return: (本次新增条数, 库内总条数)
    """
    import akshare as ak

    start = _start_date(code, market)
    end = datetime.now().strftime("%Y%m%d")
    try:
        if market == "hk":
            df = ak.stock_hk_hist(
                symbol=code[-5:], period="daily",
                start_date=start.replace("-", ""), end_date=end,
                adjust="qfq",
            )
        else:
            df = ak.stock_zh_a_hist(
                symbol=code[-6:], period="daily",
                start_date=start.replace("-", ""), end_date=end,
                adjust="qfq",
            )
        if df is None or df.empty:
            raise RuntimeError(f"{code} K 线回填无数据（起点 {start}）")

        date_col = "日期" if "日期" in df.columns else "date"
        rows = [
            (str(r[date_col])[:10], float(r["开盘"]), float(r["收盘"]),
             float(r["最高"]), float(r["最低"]), float(r["成交量"]))
            for _, r in df.iterrows()
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare K 线回填失败，降级腾讯分段拉取: %s", exc)
        rows = _backfill_kline_tencent(code, market, start)

    new = record_klines(rows, market, code)
    from .storage import count_klines

    return new, count_klines(code, market)


def _backfill_kline_tencent(code: str, market: str, start: str) -> list[tuple]:
    """腾讯 K 线按日期窗口分段拉全量。

    接口支持日期参数：fqkline/get?param={sym},day,{start},{end},800,qfq
    每窗口最多 800 根，循环推进直到覆盖今天。
    """
    import requests

    if market == "hk":
        symbol = f"hk{code[-5:]}"
        api = "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
    else:
        from .providers.base import get_market_prefix

        symbol = get_market_prefix(code) + code[-6:]
        api = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    all_rows: list[tuple] = []
    win_start = datetime.strptime(start, "%Y-%m-%d")
    today = datetime.now()
    guard = 0
    while win_start < today and guard < 100:
        guard += 1
        # 数据已推进到今日（00:00 < now 的时间差会导致空窗口），直接收尾
        if win_start.date() >= today.date():
            break
        win_end = min(win_start + timedelta(days=1120), today)  # ≈800 交易日
        url = (f"{api}?param={symbol},day,{win_start:%Y-%m-%d},{win_end:%Y-%m-%d},800,qfq")
        resp = requests.get(url, timeout=20, headers=headers)
        resp.raise_for_status()
        from .analysis import _parse_tencent_kline

        df = _parse_tencent_kline(resp.json(), symbol, code)
        if df.empty:
            break
        batch = [
            (str(r["日期"])[:10], float(r["开盘"]), float(r["收盘"]),
             float(r["最高"]), float(r["最低"]), float(r["成交量"]))
            for _, r in df.iterrows()
        ]
        all_rows.extend(batch)
        last_date = batch[-1][0]
        if last_date >= today.strftime("%Y-%m-%d"):
            break
        win_start = datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)
    if not all_rows:
        raise RuntimeError(f"腾讯 K 线分段拉取 {code} 无数据")
    return all_rows


def backfill_news(code: str, years: int = 30) -> dict:
    """回填公告与研报（按年循环东财接口，入库去重）。

    :return: {"announcements": 新增, "reports": 新增}
    """
    from .announcements import (
        _ANNOUNCE_API,
        _REPORT_API,
        _HEADERS,
        parse_announcements,
        parse_research_reports,
    )
    import requests

    code6 = code[-6:]
    ann_new = 0
    rep_new = 0

    # 公告：分页拉全量（每页 100，最多 10 页 ≈ 1000 条）
    for page in range(1, 11):
        resp = requests.get(
            _ANNOUNCE_API,
            params={
                "sr": -1, "page_size": 100, "page_index": page,
                "ann_type": "A", "client_source": "web", "stock_list": code6,
            },
            headers=_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        items = parse_announcements(resp.json())
        if not items:
            break
        new, _ = record_announcements(items, code)
        ann_new += new
        if len(items) < 100:
            break

    # 研报：按年循环（接口需 beginTime/endTime）
    end = datetime.now()
    for y in range(end.year - years, end.year + 1):
        begin = f"{y}-01-01"
        e = f"{y}-12-31"
        resp = requests.get(
            _REPORT_API,
            params={
                "pageSize": 100, "pageNo": 1, "qType": 0, "code": code6,
                "beginTime": begin, "endTime": e,
            },
            headers=_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        items = parse_research_reports(resp.json())
        if not items:
            continue
        new, _ = record_research_reports(items, code)
        rep_new += new

    return {"announcements": ann_new, "reports": rep_new}


def backfill_financial(code: str, market: str = "ashare") -> tuple[int, int]:
    """回填财报全量页。

    :param market: ashare（东财业绩报表分页）/ hk（东财港股财务指标，年度）
    :return: (本次新增条数, 库内总条数)
    """
    from .fundamentals import (
        _FIN_API,
        _FIN_API_HK,
        _HEADERS,
        parse_financials,
        parse_financials_hk,
    )
    import requests

    code6 = code[-6:]
    new = 0
    if market == "hk":
        resp = requests.get(
            _FIN_API_HK,
            params={
                "reportName": "RPT_HKF10_FN_MAININDICATOR",
                "columns": "HKF10_FN_MAININDICATOR",
                "quoteColumns": "",
                "pageNumber": "1", "pageSize": "20",
                "sortTypes": "-1", "sortColumns": "STD_REPORT_DATE",
                "filter": f'(SECUCODE="{code6}.HK")(DATE_TYPE_CODE="001")',
                "source": "F10", "client": "PC",
            },
            headers=_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        items = parse_financials_hk(
            (resp.json().get("result") or {}).get("data") or []
        )
        if items:
            new, _ = record_financials(items, code)
    else:
        for page in range(1, 10):
            resp = requests.get(
                _FIN_API,
                params={
                    "reportName": "RPT_LICO_FN_CPD",
                    "columns": "ALL",
                    "filter": f'(SECURITY_CODE="{code6}")',
                    "pageSize": 100, "pageNumber": page,
                    "sortColumns": "REPORTDATE", "sortTypes": -1,
                },
                headers=_HEADERS, timeout=15,
            )
            resp.raise_for_status()
            items = parse_financials(
                (resp.json().get("result") or {}).get("data") or []
            )
            if not items:
                break
            n, _ = record_financials(items, code)
            new += n
            if len(items) < 100:
                break

    from .storage import load_financials

    return new, len(load_financials(code))


def backfill_all(code: str, market: str, with_kline: bool = True,
                 with_news: bool = True, with_financial: bool = True) -> dict:
    """回填全部数据，返回各维度结果。"""
    result: dict = {}
    if with_kline:
        try:
            new, total = backfill_kline(code, market)
            result["kline"] = {"new": new, "total": total}
        except Exception as exc:  # noqa: BLE001
            logger.warning("K 线回填失败: %s", exc)
            result["kline"] = {"error": str(exc)}
    if with_news and market == "ashare":
        try:
            result["news"] = backfill_news(code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("公告/研报回填失败: %s", exc)
            result["news"] = {"error": str(exc)}
    if with_financial:
        try:
            new, total = backfill_financial(code, market)
            result["financial"] = {"new": new, "total": total}
        except Exception as exc:  # noqa: BLE001
            logger.warning("财报回填失败: %s", exc)
            result["financial"] = {"error": str(exc)}
    return result


def analyze_history(rows: list[dict]) -> dict:
    """基于入库日 K 计算"自上市以来"统计（纯函数，便于测试）。

    :param rows: load_klines 结果（按日期升序）
    """
    if len(rows) < 2:
        raise RuntimeError("K 线数据不足（少于 2 个交易日）")

    first = rows[0]
    last = rows[-1]
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]

    high_idx = max(range(len(highs)), key=lambda i: highs[i])
    low_idx = min(range(len(lows)), key=lambda i: lows[i])

    cur = closes[-1]
    all_time_high = highs[high_idx]
    all_time_low = lows[low_idx]
    # 当前价在历史区间的位置（0-100，100 = 历史最高）
    position = (
        (cur - all_time_low) / (all_time_high - all_time_low) * 100
        if all_time_high > all_time_low else 50.0
    )

    days = len(rows)
    years = days / 250
    # 前复权后早期价格可能为负/零（巨额分红所致），保护计算
    growth = cur / first["close"] if first["close"] > 0 else None
    total_return = (growth - 1) * 100 if growth is not None else None
    annualized = (
        ((growth ** (1 / years)) - 1) * 100
        if growth is not None and growth > 0 and years > 0.5 else None
    )
    drawdown_from_high = (cur / all_time_high - 1) * 100

    # 近一年
    year_ago = rows[-252] if days > 252 else rows[0]
    year_return = (cur / year_ago["close"] - 1) * 100
    year_high = max(highs[-252:])
    year_low = min(lows[-252:])

    return {
        "first_date": first["date"],
        "last_date": last["date"],
        "bars": days,
        "years": round(years, 1),
        "first_close": first["close"],
        "latest_close": cur,
        "total_return_pct": round(total_return, 2) if total_return is not None else None,
        "annualized_pct": round(annualized, 2) if annualized is not None else None,
        "all_time_high": all_time_high,
        "all_time_high_date": rows[high_idx]["date"],
        "all_time_low": all_time_low,
        "all_time_low_date": rows[low_idx]["date"],
        "position_pct": round(position, 1),
        "drawdown_pct": round(drawdown_from_high, 2),
        "year_return_pct": round(year_return, 2),
        "year_high": year_high,
        "year_low": year_low,
    }
