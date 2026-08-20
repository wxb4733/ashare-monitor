"""被监控标的的公告与公开报告（研报）信息。

数据源（自动降级）：
1. 东方财富公告接口 np-anotice-stock.eastmoney.com（直连，无需鉴权）
2. 东方财富研报接口 reportapi.eastmoney.com
3. akshare 兜底（stock_notice_report / stock_research_report_em）

仅支持 A 股（港股/币安无此数据源）。解析函数与网络解耦，便于测试。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}

_ANNOUNCE_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"
_REPORT_API = "https://reportapi.eastmoney.com/report/list"

# 公告详情页（东财网页版）
def _announce_url(art_code: str) -> str:
    return (
        "https://np-anotice-stock.eastmoney.com/api/content/ann"
        f"?art_code={art_code}&client_source=web&page_index=1"
    )


# 研报详情页（东财网页版）
def _report_url(info_code: str) -> str:
    return f"https://data.eastmoney.com/report/info/{info_code}.html"


def fetch_announcements(code: str, limit: int = 30) -> list[dict]:
    """拉取个股最近公告（按发布时间倒序）。

    :return: [{"date", "title", "url"}]
    :raises RuntimeError: 所有数据源均失败
    """
    try:
        return _fetch_announcements_em(code, limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("东财公告接口失败，降级 akshare: %s", exc)
        return _fetch_announcements_ak(code, limit)


def _fetch_announcements_em(code: str, limit: int) -> list[dict]:
    resp = requests.get(
        _ANNOUNCE_API,
        params={
            "sr": -1, "page_size": limit, "page_index": 1,
            "ann_type": "A", "client_source": "web", "stock_list": code[-6:],
        },
        headers=_HEADERS, timeout=10,
    )
    resp.raise_for_status()
    return parse_announcements(resp.json())


def parse_announcements(data: dict) -> list[dict]:
    """解析东财公告 JSON（独立出来便于测试）。"""
    items = (data.get("data") or {}).get("list") or []
    result = []
    for it in items:
        title = it.get("title") or it.get("title_ch") or ""
        # 去掉 "600519:贵州茅台" 前缀
        if ":" in title:
            title = title.split(":", 1)[1]
        date = (it.get("notice_date") or "")[:10]
        result.append({
            "date": date,
            "title": title,
            "url": _announce_url(it.get("art_code", "")),
        })
    return result


def _fetch_announcements_ak(code: str, limit: int) -> list[dict]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(f"akshare 未安装（可选依赖）: {exc}")

    df = ak.stock_notice_report(symbol="全部", date=datetime.now().strftime("%Y%m%d"))
    if df is None or df.empty:
        raise RuntimeError("akshare 公告为空")
    df = df[df["股票代码"].astype(str).str[-6:] == code[-6:]].head(limit)
    return [
        {
            "date": str(r["公告日期"])[:10],
            "title": str(r["公告标题"]),
            "url": str(r.get("公告链接", "")),
        }
        for _, r in df.iterrows()
    ]


def fetch_research_reports(code: str, days: int = 90, limit: int = 30) -> list[dict]:
    """拉取个股最近研报（按发布时间倒序）。

    :return: [{"date", "title", "org", "eps_this_year", "pe_this_year", "url"}]
    :raises RuntimeError: 所有数据源均失败
    """
    try:
        return _fetch_reports_em(code, days, limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("东财研报接口失败，降级 akshare: %s", exc)
        return _fetch_reports_ak(code, limit)


def _fetch_reports_em(code: str, days: int, limit: int) -> list[dict]:
    end = datetime.now()
    begin = end - timedelta(days=days)
    resp = requests.get(
        _REPORT_API,
        params={
            "pageSize": limit, "pageNo": 1, "qType": 0, "code": code[-6:],
            "beginTime": begin.strftime("%Y-%m-%d"),
            "endTime": end.strftime("%Y-%m-%d"),
        },
        headers=_HEADERS, timeout=10,
    )
    resp.raise_for_status()
    return parse_research_reports(resp.json())


def parse_research_reports(data: dict) -> list[dict]:
    """解析东财研报 JSON（独立出来便于测试）。"""
    result = []
    for it in data.get("data") or []:
        result.append({
            "date": (it.get("publishDate") or "")[:10],
            "title": it.get("title", ""),
            "org": it.get("orgSName", ""),
            "eps_this_year": _safe_float(it.get("predictThisYearEps")),
            "pe_this_year": _safe_float(it.get("predictNextYearPe")),
            "url": _report_url(it.get("infoCode", "")),
        })
    return result


def _fetch_reports_ak(code: str, limit: int) -> list[dict]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(f"akshare 未安装（可选依赖）: {exc}")

    df = ak.stock_research_report_em(symbol=code[-6:])
    if df is None or df.empty:
        raise RuntimeError("akshare 研报为空")
    df = df.head(limit)
    return [
        {
            "date": str(r["日期"])[:10],
            "title": str(r["报告名称"]),
            "org": str(r["机构"]),
            "eps_this_year": _safe_float(r.get("预测EPS")),
            "pe_this_year": _safe_float(r.get("预测PE")),
            "url": str(r.get("链接", "")),
        }
        for _, r in df.iterrows()
    ]


def _safe_float(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- 重大事项识别 ----------

# 高影响公告关键词（命中即视为重大事项，复盘/news 中标红置顶）
MAJOR_KEYWORDS = (
    # 业绩类
    "业绩预告", "业绩快报", "业绩预增", "业绩预减", "业绩预亏", "扭亏",
    "业绩说明会", "业绩交流",
    # 分红与股本
    "分红", "派息", "利润分配", "转增", "送股", "股本变动",
    # 重组并购
    "重组", "收购", "并购", "重大资产", "股权转让", "要约收购", "出售资产",
    # 融资
    "非公开发行", "定增", "配股", "可转债", "可转换", "发债", "中期票据",
    # 治理与风险
    "停牌", "复牌", "立案", "处罚", "违规", "警示函", "问询函", "监管函",
    "减持", "增持", "回购", "股权激励", "重大合同", "中标", "更名",
    "破产", "清算", "退市", "风险警示", "ST", "解禁", "诉讼", "仲裁",
    # 定期报告
    "年报", "半年报", "季度报告", "一季报", "三季报", "定期报告",
)


def is_major(title: str) -> bool:
    """判断公告标题是否属于重大事项。"""
    return any(kw in title for kw in MAJOR_KEYWORDS)
