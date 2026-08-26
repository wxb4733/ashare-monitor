"""历史数据回填：自上市以来的全量行情 / 公告 / 研报 / 财报。

- backfill_kline：日 K 全量入库（A 股 akshare stock_zh_a_hist；港股 akshare stock_hk_hist）
- backfill_news：公告/研报多页拉取入库（东财接口分页/按年）
- backfill_financial：财报全量页入库（东财业绩报表分页）

入库到 data/ashare_monitor.db（klines / announcements / research_reports / financials 表）。
"""

from __future__ import annotations

import logging
import time
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
    # 币安交易对（币安 2017-08 上线 BTCUSDT；更早数据币安无）
    ("crypto", "BTCUSDT"): "2017-08-01",
    ("crypto", "ETHUSDT"): "2017-08-01",
}


def _start_date(code: str, market: str) -> str:
    return KNOWN_IPO_DATES.get((market, code), "1990-01-01")


def backfill_kline(code: str, market: str) -> tuple[int, int]:
    """回填日 K 全量（akshare 优先，腾讯 K 线按日期窗口分段降级）。

    :return: (本次新增条数, 库内总条数)
    """
    import akshare as ak

    start = _start_date(code, market)
    end = datetime.now().strftime("%Y%m%d")
    if market == "crypto":
        # 币：Binance 双域回退（2017 起）+ CoinGecko 补更早历史（收盘价近似）
        rows = _backfill_kline_binance(code, start)
        if code.upper() in _COINGECKO_IDS:
            try:
                cg = _backfill_kline_coingecko(code, start)
                if cg:
                    cg_dates = {c[0] for c in cg}
                    rows = cg + [r for r in rows if r[0] not in cg_dates]
                    logger.info("CoinGecko 补充 %d 根（%s 之前）", len(cg), start)
            except Exception as exc:  # noqa: BLE001
                logger.warning("CoinGecko 补充失败（境外 API 可能不可达）: %s", exc)
    else:
        try:
            if market == "us":
                df = ak.stock_us_daily(symbol=code, adjust="qfq")
                if df is None or df.empty:
                    raise RuntimeError(f"{code} 美股 K 线无数据")
                rows = [
                    (str(r["date"])[:10], float(r["open"]), float(r["close"]),
                     float(r["high"]), float(r["low"]), float(r["volume"]))
                    for _, r in df.iterrows()
                ]
            elif market == "hk":
                df = ak.stock_hk_hist(
                    symbol=code[-5:], period="daily",
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
            try:
                rows = _backfill_kline_tencent(code, market, start)
            except Exception as exc2:  # noqa: BLE001
                logger.warning("腾讯 K 线降级失败，切新浪兜底: %s", exc2)
                rows = _backfill_kline_sina(code, market, start)

    new = record_klines(rows, market, code)
    from .storage import count_klines

    return new, count_klines(code, market)


def _backfill_kline_sina(code: str, market: str, start: str) -> list[tuple]:
    """新浪日 K 兜底源：最近 1023 根（约 4 年，jsonp getKLineData）。

    腾讯 fqkline 被限流（IP 级 501 反爬页持续数十分钟）时兜底；
    不足全量，仅保证体检 K 线维度有数据，限流解除后可再补全量（幂等）。
    """
    import json as _json
    import re

    import requests

    from .providers.base import get_market_prefix

    if market == "hk":
        symbol = f"hk{code[-5:]}"
    else:
        symbol = get_market_prefix(code) + code[-6:]
    url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_x="
           f"/CN_MarketDataService.getKLineData?symbol={symbol}"
           "&scale=240&ma=no&datalen=1023")
    resp = requests.get(url, timeout=20,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"})
    resp.raise_for_status()
    m = re.search(r"\((\[.*\])\)", resp.text)
    if not m:
        raise RuntimeError(f"新浪 K 线 {code} 响应解析失败")
    try:
        data = _json.loads(m.group(1))
    except ValueError:
        data = eval(m.group(1))  # noqa: S307 - 内容为受控 K 线 JSONP
    rows = [(str(r["day"])[:10], float(r["open"]), float(r["close"]),
             float(r["high"]), float(r["low"]), float(r["volume"]))
            for r in data]
    if not rows:
        raise RuntimeError(f"新浪 K 线 {code} 无数据")
    logger.info("新浪 K 线兜底 %s: %d 根（%s ~ %s）",
                code, len(rows), rows[0][0], rows[-1][0])
    return rows


def _backfill_kline_binance(code: str, start: str) -> list[tuple]:
    """币安日 K 全量分段回填（每段 1000 根，startTime 推进；双域回退）。"""
    from datetime import timezone as _tz

    from .providers.binance import _get

    base_ts = int(datetime.strptime(start, "%Y-%m-%d")
                  .replace(tzinfo=_tz.utc).timestamp() * 1000)
    end_ts = int(datetime.now().timestamp() * 1000)
    all_rows: list[tuple] = []
    cur = base_ts
    guard = 0
    while cur < end_ts and guard < 20:
        guard += 1
        resp = _get("/api/v3/klines", {
            "symbol": code.upper(), "interval": "1d",
            "startTime": cur, "endTime": end_ts, "limit": 1000,
        })
        batch = resp.json()
        if not batch:
            break
        for k in batch:
            d = datetime.fromtimestamp(int(k[0]) / 1000,
                                       tz=_tz.utc).strftime("%Y-%m-%d")
            all_rows.append((d, float(k[1]), float(k[4]), float(k[2]),
                             float(k[3]), float(k[5])))
        cur = int(batch[-1][0]) + 1
        if len(batch) < 1000:
            break
    return all_rows


# CoinGecko id 映射（补 Binance 上线前的更早历史）
_COINGECKO_IDS = {"BTCUSDT": "bitcoin", "ETHUSDT": "ethereum"}


def _backfill_kline_coingecko(code: str, before_date: str) -> list[tuple]:
    """CoinGecko 全历史日价补数据（Binance 起点之前）。

    注意（如实）：market_chart 只提供收盘价——补充段 OHLC 用收盘价近似，
    volume 记 0。仅返回 before_date 之前的日期（与 Binance 段无缝衔接）。
    """
    import requests
    from datetime import timezone as _tz

    cid = _COINGECKO_IDS.get(code.upper())
    if not cid:
        return []
    resp = requests.get(
        f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart",
        params={"vs_currency": "usd", "days": "max"},
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=25,
    )
    resp.raise_for_status()
    prices = resp.json().get("prices") or []
    cutoff = datetime.strptime(before_date, "%Y-%m-%d").date()
    rows: list[tuple] = []
    for ts, px in prices:
        d = datetime.fromtimestamp(ts / 1000, tz=_tz.utc).date()
        if d >= cutoff:
            break  # prices 按时间升序，到达 Binance 起点即停
        price = float(px)
        rows.append((d.strftime("%Y-%m-%d"), price, price, price, price, 0.0))
    return rows


def _backfill_kline_tencent(code: str, market: str, start: str) -> list[tuple]:
    """腾讯 K 线按日期窗口分段拉全量。

    接口支持日期参数：fqkline/get?param={sym},day,{start},{end},800,qfq
    每窗口最多 800 根，循环推进直到覆盖今天。
    """
    import requests

    if market == "hk":
        symbol = f"hk{code[-5:]}"
        api = "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
        hosts = ["https://web.ifzq.gtimg.cn"]
    else:
        from .providers.base import get_market_prefix

        symbol = get_market_prefix(code) + code[-6:]
        api_path = "/appstock/app/fqkline/get"
        # 域名级降级：web.ifzq 被限流（501 反爬页）时切 proxy.finance.qq.com
        hosts = ["https://web.ifzq.gtimg.cn",
                 "https://proxy.finance.qq.com/ifzqgtimg"]
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
        url_path = (f"{api_path}?param={symbol},day,{win_start:%Y-%m-%d},"
                    f"{win_end:%Y-%m-%d},800,qfq")
        # 腾讯间歇性反爬：501 返回 HTML 校验页（非 JSON）→ 退避重试 + 域名降级
        resp = None
        for host in hosts:
            for attempt in range(2):
                try:
                    resp = requests.get(host + url_path, timeout=20,
                                        headers=headers)
                except requests.RequestException:
                    resp = None
                ct = resp.headers.get("content-type", "") if resp else ""
                if resp and resp.status_code == 200 and "json" in ct:
                    break
                time.sleep(4 * (attempt + 1))  # 4s / 8s 退避
            if resp and resp.status_code == 200 and "json" in ct:
                break
            logger.warning("腾讯 K 线 %s 域名 %s 限流，降级切换", code, host)
        if resp is None or resp.status_code != 200 or "json" not in (
                resp.headers.get("content-type", "")):
            # 全部域名重试仍被限流：视作该窗口无数据，推进窗口继续
            logger.warning("腾讯 K 线 %s 窗口 %s 限流跳过",
                           code, win_start.date())
            win_start = win_end + timedelta(days=1)
            continue
        from .analysis import _parse_tencent_kline

        try:
            df = _parse_tencent_kline(resp.json(), symbol, code)
        except RuntimeError:
            # 窗口无数据（如起点早于上市日）→ 推进窗口继续，不终止
            win_start = win_end + timedelta(days=1)
            continue
        if df.empty:
            win_start = win_end + timedelta(days=1)
            continue
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


def backfill_kline_incremental(codes: list[tuple[str, str]], days: int = 15) -> dict:
    """K 线增量更新：从库内最新日期起补最近 days 天（幂等）。

    :param codes: [(code, market), ...]
    :return: {code: (新增条数, 库内总条数)}
    """
    from datetime import datetime as _dt, timedelta as _td
    from .storage import count_klines, load_klines, record_klines

    result: dict[str, tuple[int, int]] = {}
    for code, market in codes:
        try:
            rows = load_klines(code, market)
            if rows:
                last = rows[-1]["date"]
                start = (_dt.strptime(last, "%Y-%m-%d")
                         - _td(days=days)).strftime("%Y-%m-%d")
            else:
                start = _start_date(code, market)
            if market == "crypto":
                new_rows = _backfill_kline_binance(code, start)
            elif market == "us":
                import akshare as ak

                df = ak.stock_us_daily(symbol=code, adjust="qfq")
                new_rows = [(str(r["date"])[:10], float(r["open"]),
                             float(r["close"]), float(r["high"]),
                             float(r["low"]), float(r["volume"]))
                            for _, r in df.iterrows()
                            if str(r["date"])[:10] >= start]
            elif market == "hk":
                import akshare as ak

                df = ak.stock_hk_hist(symbol=code[-5:], period="daily",
                                      start_date=start.replace("-", ""),
                                      end_date=_dt.now().strftime("%Y%m%d"),
                                      adjust="qfq")
                new_rows = [(str(r["日期"])[:10], float(r["开盘"]),
                             float(r["收盘"]), float(r["最高"]),
                             float(r["最低"]), float(r["成交量"]))
                            for _, r in df.iterrows()]
            else:
                import akshare as ak

                df = ak.stock_zh_a_hist(symbol=code[-6:], period="daily",
                                        start_date=start.replace("-", ""),
                                        end_date=_dt.now().strftime("%Y%m%d"),
                                        adjust="qfq")
                new_rows = [(str(r["日期"])[:10], float(r["开盘"]),
                             float(r["收盘"]), float(r["最高"]),
                             float(r["最低"]), float(r["成交量"]))
                            for _, r in df.iterrows()]
            new = record_klines(new_rows, market, code)
            result[code] = (new, count_klines(code, market))
        except Exception as exc:  # noqa: BLE001
            result[code] = (0, 0)
            logger.warning("增量更新 %s(%s) 失败: %s", code, market,
                           str(exc)[:50])
    return result
