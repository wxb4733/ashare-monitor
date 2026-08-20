"""IPO 公司分析模块。

数据源：东方财富数据中心新股申购/上市报表 RPTA_APP_IPOAPPLY（直连，无需鉴权）。

提供：
- 近期新股列表（申购/上市日历，按申购日倒序）
- 单只新股详情（发行价、募资、行业、主营、保荐机构等）
- 规则化分析：发行阶段、发行 PE vs 行业 PE、募资完成度、上市表现（破发提示）

仅支持 A 股。解析函数与网络解耦，便于测试。

声明：IPO 分析为投资参考信息，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}

_IPO_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"


@dataclass
class IPORecord:
    code: str
    name: str
    market: str                       # 交易所
    industry: str                     # 行业
    apply_date: str                   # 申购日 YYYY-MM-DD（无则空）
    listing_date: str                 # 上市日（无则空）
    issue_price: float | None         # 发行价
    issue_pe: float | None            # 发行市盈率（发行价/每股收益 估算，缺失为 None）
    industry_pe: float | None         # 行业市盈率
    raise_funds: float | None         # 实际募资（亿元）
    plan_funds: float | None          # 计划募资（亿元）
    issue_num: float | None           # 发行量（万股）
    main_business: str                # 主营业务
    underwriter: str                  # 保荐机构
    newest_price: float | None        # 上市后最新价（未上市为 None）

    @property
    def pe_ratio(self) -> float | None:
        """发行 PE / 行业 PE。"""
        if self.issue_pe is not None and self.industry_pe:
            return self.issue_pe / self.industry_pe
        return None

    def stage(self, now: datetime | None = None) -> str:
        """发行阶段：待定价 / 待申购 / 待上市 / 已上市。"""
        now = now or datetime.now()
        today = now.strftime("%Y-%m-%d")
        if self.newest_price is not None or (self.listing_date and self.listing_date <= today):
            return "已上市"
        if self.issue_price is None:
            return "待定价"
        if self.apply_date and self.apply_date > today:
            return "待申购"
        return "待上市"


def fetch_ipo_list(limit: int = 50) -> list[IPORecord]:
    """拉取近期新股列表（按申购日倒序）。"""
    resp = requests.get(
        _IPO_API,
        params={
            "reportName": "RPTA_APP_IPOAPPLY",
            "columns": "ALL",
            "pageSize": limit, "pageNumber": 1,
            "sortColumns": "APPLY_DATE", "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        },
        headers=_HEADERS, timeout=12,
    )
    resp.raise_for_status()
    data = (resp.json().get("result") or {}).get("data") or []
    items = parse_ipo_list(data)
    if not items:
        raise RuntimeError("未获取到新股数据")
    return items


def parse_ipo_list(data: list[dict]) -> list[IPORecord]:
    """解析东财新股报表 JSON（独立出来便于测试）。"""
    result = []
    for it in data:
        issue_price = _to_float(it.get("ISSUE_PRICE"))
        # 发行市盈率：优先发行价/每股收益
        eps = _to_float(it.get("PER_SHARES_INCOME"))
        issue_pe = (
            issue_price / eps if issue_price is not None and eps else
            _to_float(it.get("PREDICT_ISSUE_PE"))
        )
        result.append(IPORecord(
            code=str(it.get("SECURITY_CODE", "")),
            name=str(it.get("SECURITY_NAME_ABBR") or it.get("SECURITY_NAME", "")),
            market=str(it.get("TRADE_MARKET", "")),
            industry=str(it.get("INDUSTRY_NAME", "")),
            apply_date=str(it.get("APPLY_DATE", ""))[:10],
            listing_date=str(it.get("LISTING_DATE", ""))[:10],
            issue_price=issue_price,
            issue_pe=round(issue_pe, 2) if issue_pe is not None else None,
            industry_pe=_to_float(it.get("INDUSTRY_PE_NEW") or it.get("INDUSTRY_PE")),
            raise_funds=_to_float(it.get("TOTAL_RAISE_FUNDS")),
            plan_funds=_to_float(it.get("PREDICT_RAISE_FUNDS")),
            issue_num=_to_float(it.get("TOTAL_ISSUE_NUM")),
            main_business=str(it.get("MAIN_BUSINESS", "")),
            underwriter=str(it.get("UNDERWRITER_ORG", "")),
            newest_price=_to_float(it.get("NEWEST_PRICE")),
        ))
    return result


def find_ipo(items: list[IPORecord], keyword: str) -> IPORecord | None:
    """按代码精确或名称包含查找。"""
    kw = keyword.strip()
    for it in items:
        if it.code == kw or kw in it.name:
            return it
    return None


def analyze_ipo(rec: IPORecord, now: datetime | None = None) -> list[str]:
    """规则化 IPO 分析（不构成投资建议）。"""
    lines = []
    stage = rec.stage(now)

    # 1. 发行阶段
    if stage == "待定价":
        lines.append("尚未定价：发行价/市盈率待公布，可关注后续询价结果")
    elif stage == "待申购":
        lines.append(f"待申购：网上申购日为 {rec.apply_date}，可提前了解发行资料")
    elif stage == "待上市":
        lines.append(f"待上市：已定价发行价 {rec.issue_price:.2f} 元，"
                     + (f"上市日 {rec.listing_date}" if rec.listing_date else "上市日待定"))
    else:
        if rec.newest_price is not None and rec.issue_price:
            change = (rec.newest_price / rec.issue_price - 1) * 100
            if change < 0:
                lines.append(
                    f"已上市且现价 {rec.newest_price:.2f} 元低于发行价 {rec.issue_price:.2f} 元"
                    f"（{change:+.1f}%），已破发，注意风险"
                )
            else:
                lines.append(
                    f"已上市：现价 {rec.newest_price:.2f} 元较发行价 {rec.issue_price:.2f} 元"
                    f"上涨 {change:+.1f}%"
                )

    # 2. 发行 PE vs 行业 PE
    ratio = rec.pe_ratio
    if ratio is not None and rec.industry_pe is not None:
        if ratio >= 1.5:
            lines.append(
                f"发行 PE {rec.issue_pe:.1f} 显著高于行业 {rec.industry_pe:.1f}"
                f"（{ratio:.2f} 倍），估值偏贵"
            )
        elif ratio <= 0.8:
            lines.append(
                f"发行 PE {rec.issue_pe:.1f} 低于行业 {rec.industry_pe:.1f}"
                f"（{ratio:.2f} 倍），估值相对便宜"
            )
        else:
            lines.append(
                f"发行 PE {rec.issue_pe:.1f} 与行业 {rec.industry_pe:.1f} 基本持平"
                f"（{ratio:.2f} 倍）"
            )
    elif rec.issue_pe is not None:
        lines.append(f"发行 PE {rec.issue_pe:.1f}（暂无行业对比）")

    # 3. 募资完成度
    if rec.raise_funds is not None and rec.plan_funds:
        ratio_f = rec.raise_funds / rec.plan_funds * 100
        if ratio_f >= 105:
            lines.append(f"实际募资 {rec.raise_funds:.2f} 亿，超募 {ratio_f - 100:.0f}%（市场认购踊跃）")
        elif ratio_f <= 95:
            lines.append(f"实际募资 {rec.raise_funds:.2f} 亿，缩募（仅计划 {rec.plan_funds:.0f} 亿的 {ratio_f:.0f}%）")
        else:
            lines.append(f"募资 {rec.raise_funds:.2f} 亿，基本达成计划（{rec.plan_funds:.0f} 亿）")

    # 4. 基本信息摘要
    if rec.main_business:
        biz = rec.main_business if len(rec.main_business) <= 60 else rec.main_business[:57] + "…"
        lines.append(f"主营：{biz}")
    if rec.underwriter:
        lines.append(f"保荐机构：{rec.underwriter}")

    return lines


def _to_float(v) -> float | None:
    try:
        if v is None or v == "" or v == "--":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
