"""A 股市场扫描选股器：第一个指标——高股息率。

数据源：东财 push2 全市场行情（f133=股息率 TTM），按股息率降序直拉 TOP N。
降级：akshare stock_zh_a_spot_em（若版本含股息率字段）。

过滤规则（可选参数）：
- min_yield：最低股息率（默认 3%）
- exclude_st：剔除 ST/*ST/退市整理（默认开启）
- min_mv / max_mv：总市值区间（亿，可选）

输出：候选表（代码/名称/现价/股息率/PE/PB/市值）+ HTML 报告。
说明：push2 东财域在部分沙箱/网络环境连接不稳（RemoteDisconnected 已知），
代码无问题，本机直连通常可用；失败时如实提示降级。
股息率 TTM 口径（f133，%），不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# 全 A 股板块（深主板/创业板/沪主板/科创板）
_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}


@dataclass
class ScreenHit:
    code: str
    name: str
    price: float | None
    dividend_yield: float | None   # 股息率 TTM %
    pe: float | None
    pb: float | None
    market_value: float | None     # 总市值（元）

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "price": self.price,
            "dividend_yield": self.dividend_yield, "pe": self.pe,
            "pb": self.pb, "market_value": self.market_value,
        }


def _f(v) -> float | None:
    try:
        if v is None or str(v).lower() in ("nan", "--", "-", ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_dividend_top(top_n: int = 60, min_yield: float = 3.0,
                       exclude_st: bool = True,
                       min_mv: float | None = None,
                       max_mv: float | None = None) -> list[ScreenHit]:
    """东财 push2 按股息率降序拉全市场 TOP，套过滤规则。"""
    import requests

    page_size = min(top_n * 2 + 50, 200)
    params = {
        "pn": 1, "pz": page_size, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f133", "fs": _FS,
        "fields": "f2,f9,f12,f14,f23,f133,f20",
    }
    resp = requests.get(
        "https://push2.eastmoney.com/api/qt/clist/get",
        params=params, headers=_HEADERS, timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    diff = (payload.get("data") or {}).get("diff") or []
    if not diff and isinstance(payload.get("data"), dict) \
            and payload["data"].get("total") is None:
        raise RuntimeError("东财行情接口返回异常（可能网络受限）")

    hits: list[ScreenHit] = []
    for r in diff:
        code = str(r.get("f12") or "")
        name = str(r.get("f14") or "")
        dy = _f(r.get("f133"))
        mv = _f(r.get("f20"))
        if dy is None or dy < min_yield:
            continue
        if exclude_st and ("ST" in name.upper() or "退" in name):
            continue
        if min_mv is not None and (mv is None or mv < min_mv * 1e8):
            continue
        if max_mv is not None and (mv is not None and mv > max_mv * 1e8):
            continue
        hits.append(ScreenHit(
            code=code, name=name, price=_f(r.get("f2")),
            dividend_yield=dy, pe=_f(r.get("f9")), pb=_f(r.get("f23")),
            market_value=mv,
        ))
    hits.sort(key=lambda x: (x.dividend_yield or 0), reverse=True)
    return hits[:top_n]


def screen_dividend(top_n: int = 60, min_yield: float = 3.0,
                    exclude_st: bool = True,
                    min_mv: float | None = None,
                    max_mv: float | None = None) -> list[ScreenHit]:
    """高股息率选股（东财 push2 → akshare 全市场行情降级）。"""
    try:
        return fetch_dividend_top(top_n, min_yield, exclude_st,
                                  min_mv, max_mv)
    except Exception as exc:  # noqa: BLE001
        logger.warning("push2 直连失败，降级 akshare: %s", exc)
    try:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        if "股息率" not in df.columns:
            raise RuntimeError(
                "当前 akshare 版本 stock_zh_a_spot_em 无股息率字段（f133），"
                "请使用东财 push2 直连（本机网络通常可用）")
        hits = []
        for _, r in df.iterrows():
            name = str(r.get("名称") or "")
            dy = _f(r.get("股息率"))
            if dy is None or dy < min_yield:
                continue
            if exclude_st and ("ST" in name.upper() or "退" in name):
                continue
            hits.append(ScreenHit(
                code=str(r.get("代码") or ""), name=name,
                price=_f(r.get("最新价")), dividend_yield=dy,
                pe=_f(r.get("市盈率-动态")), pb=_f(r.get("市净率")),
                market_value=_f(r.get("总市值")),
            ))
        hits.sort(key=lambda x: (x.dividend_yield or 0), reverse=True)
        return hits[:top_n]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"高股息率选股数据源均不可用：{exc}（东财 push2 在部分环境受限，"
            "请在本机直连验证）") from exc


def build_screen_report(hits: list[ScreenHit], metric: str,
                        params: dict, as_of: str | None = None) -> tuple[str, str]:
    """生成选股报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _mv(v: float | None) -> str:
        if v is None:
            return "-"
        return f"{v / 1e8:.0f} 亿"

    tr = []
    md_rows = ["| 代码 | 名称 | 现价 | 股息率% | PE | PB | 总市值 |",
               "| --- | --- | --- | --- | --- | --- | --- |"]
    for i, h in enumerate(hits, 1):
        price_c = (f"<td>{h.price:.2f}</td>"
                   if h.price is not None else "<td>-</td>")
        dy_c = (f'<td><span style="color:#e02e24;font-weight:600">'
                f'{h.dividend_yield:.2f}</span></td>')
        pe_c = f"<td>{h.pe:.1f}</td>" if h.pe is not None else "<td>-</td>"
        pb_c = f"<td>{h.pb:.2f}</td>" if h.pb is not None else "<td>-</td>"
        mv_c = f"<td>{_mv(h.market_value)}</td>"
        tr.append(f"<tr><td>{i}</td><td>{h.name}</td><td>{h.code}</td>"
                  f"{price_c}{dy_c}{pe_c}{pb_c}{mv_c}</tr>")
        price_s = f"{h.price:.2f}" if h.price is not None else "-"
        pe_s = f"{h.pe:.1f}" if h.pe is not None else "-"
        pb_s = f"{h.pb:.2f}" if h.pb is not None else "-"
        md_rows.append(f"| {h.code} | {h.name} | {price_s} | "
                       f"**{h.dividend_yield:.2f}** | {pe_s} | {pb_s} | "
                       f"{_mv(h.market_value)} |")

    param_note = "，".join(f"{k}={v}" for k, v in params.items())
    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
.meta { color: #86909c; font-size: 12px; margin-bottom: 16px; }
.card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; }
th { background: #fafafa; color: #666; font-weight: 600; }
th:first-child, td:first-child { text-align: left; }
.footer { color: #86909c; font-size: 12px; text-align: center; padding: 16px 0 8px; }
"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{metric}选股 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>{metric}选股（{len(hits)} 只）</h1>
<div class="meta">{as_of} · 参数：{param_note} · 数据来源：东财行情（股息率 TTM）· 涨红跌绿</div>
<div class="card"><table>
<tr><th>#</th><th>名称</th><th>代码</th><th>现价</th><th>股息率%</th><th>PE</th><th>PB</th><th>总市值</th></tr>
{''.join(tr) if tr else '<tr><td colspan="8" style="text-align:center;color:#86909c">无结果（提高阈值或放宽过滤）</td></tr>'}
</table></div>
<div class="footer">股息率 TTM 口径；高股息不代表低风险，需结合基本面/分红可持续性。
不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: {metric}选股 {as_of}
date: {as_of}
tags: [选股, {metric}]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# {metric}选股 {as_of}

参数：{param_note}

{chr(10).join(md_rows) if md_rows else "无结果。"}

> 高股息不代表低风险，不构成投资建议。
"""
    return html, md


# ===================== 指标 2：持续增长率（SGR） =====================

# SGR = ROE × (1 - 股利支付率)。衡量内生可持续增长（不靠外部融资/杠杆）。
# 口径（如实）：2025 年报加权 ROE × 留存率；
# 支付率 = 2025 年度每股派息 / 2025 年报 EPS（clamp 0~1，EPS≤0 排除）。
# 数据源：东财业绩报表（RPT_LICO_FN_CPD）+ 东财分红送配报表（stock_fhps_em）。

_REPORT_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_REPORT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://data.eastmoney.com/",
}


def _fetch_report_page(report_date: str, page: int,
                       page_size: int = 500) -> tuple[list[dict], int]:
    """拉一页业绩报表。返回 (rows, count)。"""
    import requests

    d = requests.get(
        _REPORT_API,
        params={
            "reportName": "RPT_LICO_FN_CPD", "columns": "ALL",
            "pageSize": page_size, "pageNumber": page,
            "filter": f"(REPORTDATE='{report_date}')",
            "sortColumns": "UPDATE_DATE", "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        },
        headers=_REPORT_HEADERS, timeout=20,
    ).json()
    res = d.get("result") or {}
    return (res.get("data") or []), (res.get("count") or 0)


def _fetch_report_all(report_date: str) -> dict[str, dict]:
    """分页拉全市场业绩报表，按代码去重（取最新更新）。"""
    rows, count = _fetch_report_page(report_date, 1)
    result: dict[str, dict] = {}
    for r in rows:
        result.setdefault(str(r.get("SECURITY_CODE") or ""), r)
    if count > 500:
        import math

        pages = math.ceil(count / 500)
        for p in range(2, min(pages + 1, 30)):
            try:
                more, _ = _fetch_report_page(report_date, p)
            except Exception:  # noqa: BLE001
                continue
            if not more:
                break
            for r in more:
                result.setdefault(str(r.get("SECURITY_CODE") or ""), r)
    return result


def screen_sgr(top_n: int = 60, min_sgr: float = 10.0,
               min_roe: float = 8.0, exclude_st: bool = True) -> list[ScreenHit]:
    """持续增长率选股：ROE × (1 - 支付率)。"""
    import akshare as ak

    # 1. 2025 年报 ROE + EPS（全市场分页）
    report = _fetch_report_all("2025-12-31")
    # 2. 2025 年度分红每股派息
    try:
        div_df = ak.stock_fhps_em(date="20251231")
    except Exception as exc:  # noqa: BLE001
        div_df = None
        logger.warning("分红报表失败: %s", exc)
    dps_map: dict[str, float] = {}
    if div_df is not None and not div_df.empty:
        code_col = div_df.columns[0]
        dps_col = next((c for c in div_df.columns
                        if "现金分红比例" in c or "现金分红-现金分红" in c), None)
        for _, r in div_df.iterrows():
            code = str(r.get(code_col) or "")
            dps10 = _f(r.get(dps_col)) if dps_col else None
            if dps10 is not None:
                dps_map[code] = dps_map.get(code, 0.0) + dps10 / 10.0

    hits = []
    for code, r in report.items():
        name = str(r.get("SECURITY_NAME_ABBR") or "")
        if exclude_st and ("ST" in name.upper() or "退" in name):
            continue
        # 排除北交所/新三板（43/83/87/92 开头）——小票 ROE 数据异常值多
        if code.startswith(("43", "83", "87", "92")):
            continue
        roe = _f(r.get("WEIGHTAVG_ROE"))
        eps = _f(r.get("BASIC_EPS"))
        if roe is None or eps is None or roe <= 0 or eps <= 0:
            continue
        if roe > 100:      # 极端值视为数据异常
            continue
        if roe < min_roe:
            continue
        dps = dps_map.get(code, 0.0)
        pay = min(dps / eps, 1.0)   # 支付率 clamp
        sgr = roe * (1 - pay)
        if sgr < min_sgr:
            continue
        hits.append(ScreenHit(
            code=code, name=name, price=None, dividend_yield=pay * 100,
            pe=None, pb=None, market_value=None,
        ))
        hits[-1]._sgr = round(sgr, 2)
        hits[-1]._roe = round(roe, 2)
    hits.sort(key=lambda x: x._sgr, reverse=True)
    return hits[:top_n]


# ===================== 指标 3：高利润率 =====================

# 净利率 = 归母净利润 / 营业总收入 × 100（最新报告期）。
# 过滤：净利率 ≥ min_margin、毛利率 > 0、净利率 < 100%（异常）、营收 ≥ min_rev（剔除微盘噪音）。
# 数据源：东财业绩报表 RPT_LICO_FN_CPD（TOTAL_OPERATE_INCOME/PARENT_NETPROFIT/XSMLL）。


def screen_margin(top_n: int = 60, min_margin: float = 15.0,
                  min_rev: float = 1.0, exclude_st: bool = True,
                  report_date: str | None = None) -> list[ScreenHit]:
    """高利润率选股：净利率 = 归母净利/营收。"""
    report_date = report_date or f"{datetime.now().year}-06-30"
    report = _fetch_report_all(report_date)

    hits = []
    for code, r in report.items():
        name = str(r.get("SECURITY_NAME_ABBR") or "")
        if exclude_st and ("ST" in name.upper() or "退" in name):
            continue
        if code.startswith(("43", "83", "87", "92")):
            continue
        rev = _f(r.get("TOTAL_OPERATE_INCOME"))
        npf = _f(r.get("PARENT_NETPROFIT"))
        gm = _f(r.get("XSMLL"))
        if rev is None or npf is None or rev <= 0 or npf <= 0:
            continue
        if rev < min_rev * 1e8:
            continue
        nm = npf / rev * 100          # 净利率 %
        if nm > 100:                  # 极端值视为异常
            continue
        if nm < min_margin:
            continue
        hits.append(ScreenHit(
            code=code, name=name, price=None, dividend_yield=nm,
            pe=None, pb=None, market_value=rev,
        ))
        hits[-1]._net_margin = round(nm, 2)
        hits[-1]._gross_margin = round(gm, 2) if gm is not None else None
        hits[-1]._net_profit = npf / 1e8   # 亿
    hits.sort(key=lambda x: x._net_margin, reverse=True)
    return hits[:top_n]
