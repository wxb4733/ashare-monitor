"""财报（财务业绩）分析模块。

数据源（自动降级）：
1. A 股：东方财富业绩报表接口 datacenter-web.eastmoney.com（RPT_LICO_FN_CPD，直连）→ akshare 兜底
2. 港股：东方财富港股财务指标（RPT_HKF10_FN_MAININDICATOR，年度口径，单位港元）→ akshare 兜底

输出最近 N 个报告期的主要财务指标与简单趋势评判。
解析函数与网络解耦，便于测试。

声明：财报分析为投资参考信息，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}

_FIN_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
# 港股财务指标（datacenter.eastmoney.com/securities 域）
_FIN_API_HK = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


@dataclass
class FinancialPeriod:
    report_date: str          # 报告期 YYYY-MM-DD
    revenue: float | None     # 营业总收入（亿元）
    net_profit: float | None  # 归母净利润（亿元）
    revenue_yoy: float | None # 营收同比 %
    profit_yoy: float | None  # 净利同比 %
    roe: float | None         # 加权 ROE %
    gross_margin: float | None  # 销售毛利率 %
    net_margin: float | None  # 净利率 %（归母净利/营收 计算）
    eps: float | None         # 基本每股收益
    ocf_per_share: float | None  # 每股经营现金流

    @property
    def profit_yoy_improving(self) -> bool | None:
        """本报告期相对上期，净利同比是否改善（用于趋势评判）。"""
        return None  # 占位，趋势由 summarize 在完整序列上判断


def fetch_financials(code: str, periods: int = 6, market: str = "ashare") -> list[FinancialPeriod]:
    """拉取个股最近 N 个报告期财务指标。

    :param market: ashare（东财业绩报表 → akshare 降级）/ hk（东财港股财务指标）
    """
    if market == "hk":
        try:
            return _fetch_financials_hk(code, periods)
        except Exception as exc:  # noqa: BLE001
            logger.warning("东财港股财报接口失败，降级 akshare: %s", exc)
            return _fetch_financials_hk_ak(code, periods)
    try:
        return _fetch_financials_em(code, periods)
    except Exception as exc:  # noqa: BLE001
        logger.warning("东财财报接口失败，降级 akshare: %s", exc)
        return _fetch_financials_ak(code, periods)


def _fetch_financials_hk(code: str, periods: int) -> list[FinancialPeriod]:
    """东财港股财务指标（RPT_HKF10_FN_MAININDICATOR，年度口径）。

    字段单位：营收/净利为港元原值（解析时转亿）、同比/比率/ROE 为 %、EPS 为元。
    """
    resp = requests.get(
        _FIN_API_HK,
        params={
            "reportName": "RPT_HKF10_FN_MAININDICATOR",
            "columns": "HKF10_FN_MAININDICATOR",
            "quoteColumns": "",
            "pageNumber": "1", "pageSize": str(max(periods, 1)),
            "sortTypes": "-1", "sortColumns": "STD_REPORT_DATE",
            "filter": f'(SECUCODE="{code}.HK")(DATE_TYPE_CODE="001")',
            "source": "F10", "client": "PC",
        },
        headers=_HEADERS, timeout=12,
    )
    resp.raise_for_status()
    data = (resp.json().get("result") or {}).get("data") or []
    periods_list = parse_financials_hk(data)
    if not periods_list:
        raise RuntimeError(f"未获取到 {code} 的港股财报数据")
    return periods_list


def parse_financials_hk(data: list[dict]) -> list[FinancialPeriod]:
    """解析东财港股财务指标 JSON 为 FinancialPeriod（倒序：最新在前）。

    港股无归母净利口径（HOLDER_PROFIT 为股东应占溢利），净利率用接口字段，缺失时按 净利/营收 计算。
    """
    result = []
    for it in data:
        revenue = _to_float(it.get("OPERATE_INCOME"))
        net_profit = _to_float(it.get("HOLDER_PROFIT"))
        revenue_yi = revenue / 1e8 if revenue is not None else None
        profit_yi = net_profit / 1e8 if net_profit is not None else None
        net_margin = _to_float(it.get("NET_PROFIT_RATIO"))
        if net_margin is None and net_profit is not None and revenue:
            net_margin = round(net_profit / revenue * 100, 2)
        result.append(FinancialPeriod(
            report_date=str(it.get("REPORT_DATE", ""))[:10],
            revenue=revenue_yi,               # 亿港元
            net_profit=profit_yi,             # 亿港元
            revenue_yoy=_to_float(it.get("OPERATE_INCOME_YOY")),
            profit_yoy=_to_float(it.get("HOLDER_PROFIT_YOY")),
            roe=_to_float(it.get("ROE_AVG")),
            gross_margin=_to_float(it.get("GROSS_PROFIT_RATIO")),
            net_margin=net_margin,
            eps=_to_float(it.get("BASIC_EPS")),
            ocf_per_share=_to_float(it.get("PER_NETCASH_OPERATE")),
        ))
    return result


def _fetch_financials_hk_ak(code: str, periods: int) -> list[FinancialPeriod]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(f"akshare 未安装（可选依赖）: {exc}")

    df = ak.stock_financial_hk_analysis_indicator_em(code, indicator="年度")
    if df is None or df.empty:
        raise RuntimeError("akshare 港股财报为空")
    items = []
    for _, r in df.head(periods).iterrows():
        revenue = _to_float(r.get("OPERATE_INCOME"))
        net_profit = _to_float(r.get("HOLDER_PROFIT"))
        net_margin = _to_float(r.get("NET_PROFIT_RATIO"))
        items.append(FinancialPeriod(
            report_date=str(r.get("REPORT_DATE", ""))[:10],
            revenue=revenue / 1e8 if revenue is not None else None,
            net_profit=net_profit / 1e8 if net_profit is not None else None,
            revenue_yoy=_to_float(r.get("OPERATE_INCOME_YOY")),
            profit_yoy=_to_float(r.get("HOLDER_PROFIT_YOY")),
            roe=_to_float(r.get("ROE_AVG")),
            gross_margin=_to_float(r.get("GROSS_PROFIT_RATIO")),
            net_margin=net_margin,
            eps=_to_float(r.get("BASIC_EPS")),
            ocf_per_share=_to_float(r.get("PER_NETCASH_OPERATE")),
        ))
    return items


def _fetch_financials_em(code: str, periods: int) -> list[FinancialPeriod]:
    resp = requests.get(
        _FIN_API,
        params={
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{code[-6:]}")',
            "pageSize": periods, "pageNumber": 1,
            "sortColumns": "REPORTDATE", "sortTypes": -1,
        },
        headers=_HEADERS, timeout=12,
    )
    resp.raise_for_status()
    data = (resp.json().get("result") or {}).get("data") or []
    periods_list = parse_financials(data)
    if not periods_list:
        raise RuntimeError(f"未获取到 {code} 的财报数据")
    return periods_list


def parse_financials(data: list[dict]) -> list[FinancialPeriod]:
    """解析东财业绩报表 JSON 为 FinancialPeriod 列表（倒序：最新在前）。"""
    result = []
    for it in data:
        revenue = _to_float(it.get("TOTAL_OPERATE_INCOME"))
        net_profit = _to_float(it.get("PARENT_NETPROFIT"))
        # 元 → 亿元
        revenue_yi = revenue / 1e8 if revenue is not None else None
        profit_yi = net_profit / 1e8 if net_profit is not None else None
        net_margin = (
            net_profit / revenue * 100
            if net_profit is not None and revenue
            else None
        )
        result.append(FinancialPeriod(
            report_date=str(it.get("REPORTDATE", ""))[:10],
            revenue=revenue_yi,
            net_profit=profit_yi,
            revenue_yoy=_to_float(it.get("YSTZ")),
            profit_yoy=_to_float(it.get("SJLTZ")),
            roe=_to_float(it.get("WEIGHTAVG_ROE")),
            gross_margin=_to_float(it.get("XSMLL")),
            net_margin=round(net_margin, 2) if net_margin is not None else None,
            eps=_to_float(it.get("BASIC_EPS")),
            ocf_per_share=_to_float(it.get("MGJYXJJE")),
        ))
    return result


def _fetch_financials_ak(code: str, periods: int) -> list[FinancialPeriod]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(f"akshare 未安装（可选依赖）: {exc}")

    df = ak.stock_financial_abstract(symbol=code[-6:])
    if df is None or df.empty:
        raise RuntimeError("akshare 财报为空")
    items = []
    for _, r in df.head(periods).iterrows():
        items.append(FinancialPeriod(
            report_date=str(r.get("报告期", ""))[:10],
            revenue=_to_float(r.get("营业总收入")),
            net_profit=_to_float(r.get("归母净利润")),
            revenue_yoy=_to_float(r.get("营业总收入-同比增长")),
            profit_yoy=_to_float(r.get("归母净利润-同比增长")),
            roe=_to_float(r.get("净资产收益率")),
            gross_margin=_to_float(r.get("销售毛利率")),
            net_margin=_to_float(r.get("销售净利率")),
            eps=_to_float(r.get("基本每股收益")),
            ocf_per_share=_to_float(r.get("每股经营现金流量净额")),
        ))
    return items


def _to_float(v) -> float | None:
    try:
        if v is None or v == "" or v == "--":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def summarize(periods: list[FinancialPeriod]) -> list[str]:
    """基于报告期序列给出简单趋势评判（规则化，不构成投资建议）。"""
    if not periods:
        return []
    latest, prev = periods[0], periods[1] if len(periods) > 1 else None
    lines = []

    if latest.revenue_yoy is not None:
        lines.append(f"最新期营收同比 {latest.revenue_yoy:+.1f}%")
    if latest.profit_yoy is not None:
        lines.append(f"净利同比 {latest.profit_yoy:+.1f}%")
    if latest.eps is not None:
        lines.append(f"EPS {latest.eps:.2f}")

    # 净利同比趋势
    if latest.profit_yoy is not None and prev is not None and prev.profit_yoy is not None:
        delta = latest.profit_yoy - prev.profit_yoy
        if delta >= 1:
            lines.append(f"净利增速环比改善（{prev.profit_yoy:+.1f}% → {latest.profit_yoy:+.1f}%）")
        elif delta <= -1:
            lines.append(f"净利增速环比放缓（{prev.profit_yoy:+.1f}% → {latest.profit_yoy:+.1f}%）")

    # 连续正增长（近 3 期）
    recent = [p.profit_yoy for p in periods[:3] if p.profit_yoy is not None]
    if len(recent) == 3 and all(v > 0 for v in recent):
        lines.append("近 3 期净利连续正增长")
    if len(recent) == 3 and all(v < 0 for v in recent):
        lines.append("近 3 期净利连续负增长（注意风险）")

    # 盈利能力
    if latest.roe is not None:
        lines.append(f"加权 ROE {latest.roe:.1f}%"
                     + ("（优秀，≥15%）" if latest.roe >= 15 else
                        ("（尚可，≥8%）" if latest.roe >= 8 else "（偏低）")))
    if latest.gross_margin is not None:
        lines.append(f"毛利率 {latest.gross_margin:.1f}%"
                     + ("（高毛利）" if latest.gross_margin >= 40 else ""))
    if latest.net_margin is not None:
        lines.append(f"净利率 {latest.net_margin:.1f}%")

    # 盈利质量：每股经营现金流 vs EPS
    if latest.ocf_per_share is not None and latest.eps is not None:
        if latest.ocf_per_share > 0 and latest.ocf_per_share >= latest.eps:
            lines.append(
                f"经营现金流（每股 {latest.ocf_per_share:.2f} 元）覆盖净利润，盈利质量好"
            )
        elif latest.ocf_per_share is not None and latest.ocf_per_share < 0:
            lines.append("每股经营现金流为负（注意资金链与利润含金量）")

    return lines
