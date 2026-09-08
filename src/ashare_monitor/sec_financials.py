"""SEC EDGAR 财报接入（经 OpenBB sec provider）——美股基本面权威源。

背景
----
- financials 表原仅 A/H 股（东财口径，CNY 亿元）；NVDA 等美股长期无权威财务数据。
- OpenBB ``sec`` provider（免 key，SEC EDGAR 官方 XBRL）返回字段口径与东财不同：
  ``operating_revenue`` / ``net_income`` / ``diluted_eps`` / ``fiscal_year`` ...
- 已知陷阱：balance 的 ``common_equity`` 是普通股面值（par value，如 NVDA
  $0.001 面值 × 245 亿股 ≈ 2400 万），**不是**股东权益。直接用会算出荒谬
  ROE（~500279%）。权益必须用恒等式 ``总资产 − 总负债`` 推算。

单位约定
--------
落库金额列 = "该币种的亿"：美国本土公司 USD 亿美元；**SEC 20-F 外国发行人
（TSM/ASML 等）按本币列报，OpenBB sec provider 不做折算**——金额为报告货币
原值，调用方须按报告货币标注真实 currency（TWD/EUR…），禁止一律标 USD
（TSM 曾因此把 2.89 万亿新台币误记为 2.89 万亿美元）。比率列为百分数；
eps 为每股原值。ocf_per_share：SEC 三表无加权股数，诚实置 ``None``（不估算）。

解析函数与网络解耦（``_obb_fetch`` 为模块级薄封装，测试可 mock）。

声明：财报分析为投资参考信息，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging

from .fundamentals import FinancialPeriod

logger = logging.getLogger(__name__)

# OpenBB sec provider 字段候选名（大写/复数容错，按序取第一个存在的列）
_INC_REV = ("operating_revenue", "operating_revenues", "revenues", "revenue")
_INC_COST = ("operating_cost_of_revenue", "cost_of_revenue", "costs_of_revenue",
             "cost_of_goods_and_services_sold")
_INC_NI = ("net_income", "net_income_loss", "profit_loss")
_INC_EPS = ("diluted_eps", "earnings_per_share_diluted",
            "earnings_per_share_basic", "basic_eps")
_BAL_ASSETS = ("total_assets", "assets")
_BAL_LIAB = ("total_liabilities", "liabilities")
_CASH_OCF = ("net_cash_from_operating_activities", "net_cash_provided_by_operating_activities")


def _norm_col(name) -> str:
    """列名归一化：小写 + 去下划线/空格（SEC XBRL 展平差异：net_income vs NetIncomeLoss）。"""
    return "".join(str(name).lower().replace("_", "").split())


def _col(df, candidates: tuple[str, ...]) -> str | None:
    """归一化后找第一个存在的列名（大小写/下划线/单复数容错）。"""
    cols = {_norm_col(c): str(c) for c in df.columns}
    for cand in candidates:
        hit = cols.get(_norm_col(cand))
        if hit:
            return hit
    return None


def _yi(x) -> float | None:
    """美元原值 → 亿美元（None 安全）。A 股 CN¥ 以"亿"为单位，美股以 USD 亿对齐。"""
    if x is None:
        return None
    try:
        return round(float(x) / 1e8, 4)
    except (TypeError, ValueError):
        return None


def _pct(x) -> float | None:
    """比率 → 百分数（None 安全；已是 % 的数原样除 1 保量级由调用方确认）。"""
    if x is None:
        return None
    try:
        return round(float(x) * 100.0, 2)
    except (TypeError, ValueError):
        return None


def _fmt_date(v) -> str | None:
    """period_ending → YYYY-MM-DD（兼容 Timestamp / date / str）。"""
    if v is None:
        return None
    return str(v)[:10]


def _as_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _obb_fetch(kind: str, symbol: str, limit: int):
    """OpenBB SEC 单表拉取——模块级薄封装，测试可 mock 点。

    kind: 'balance' | 'income' | 'cash'
    返回 pandas DataFrame（列 = SEC XBRL 展平字段）。
    """
    from openbb import obb  # 可选依赖：pip install -e ".[openbb]"

    fn = {
        "balance": obb.equity.fundamental.balance,
        "income": obb.equity.fundamental.income,
        "cash": obb.equity.fundamental.cash,
    }[kind]
    res = fn(symbol, provider="sec", period="annual", limit=limit)
    return res.to_dataframe()


def fetch_sec_financials(code: str, periods: int = 5) -> list[FinancialPeriod]:
    """拉取美股最近 N 个财年的 SEC 财报，映射为 FinancialPeriod（USD 亿口径）。

    :param code: 美股代码（NVDA / MSFT …）
    :param periods: 输出财年数（内部拉 periods+1 期用于算同比）
    :raises RuntimeError: OpenBB 未安装 / 网络失败 / 无数据
    """
    try:
        from openbb import obb  # noqa: F401  # 前置检查，给出清晰错误
    except ImportError as exc:
        raise RuntimeError('OpenBB 未安装（pip install -e ".[openbb]"）') from exc

    if periods < 1:
        raise ValueError("periods 必须 >= 1")
    limit = periods + 1  # 多拉一期供相邻财年 YoY
    try:
        bal_df = _obb_fetch("balance", code, limit)
        inc_df = _obb_fetch("income", code, limit)
        cash_df = _obb_fetch("cash", code, limit)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"OpenBB SEC {code} 三表拉取失败: {exc}") from exc

    if inc_df is None or inc_df.empty:
        raise RuntimeError(f"OpenBB SEC {code} income 无数据")

    rev_col = _col(inc_df, _INC_REV)
    cost_col = _col(inc_df, _INC_COST)
    ni_col = _col(inc_df, _INC_NI)
    eps_col = _col(inc_df, _INC_EPS)
    assets_col = _col(bal_df, _BAL_ASSETS)
    liab_col = _col(bal_df, _BAL_LIAB)
    ocf_col = _col(cash_df, _CASH_OCF)

    def fy_of(r, fy_col: str | None) -> int | None:
        if fy_col is None:
            return None
        return _as_int(r[fy_col])

    fy_col_bal = _col(bal_df, ("fiscal_year",)) if bal_df is not None else None
    fy_col_inc = _col(inc_df, ("fiscal_year",))
    fy_col_cash = _col(cash_df, ("fiscal_year",)) if cash_df is not None else None

    # balance/cash 按财年建索引
    bal_by_fy: dict[int, dict] = {}
    if bal_df is not None and not bal_df.empty and assets_col:
        for _, r in bal_df.iterrows():
            fy = fy_of(r, fy_col_bal)
            if fy is None:
                continue
            bal_by_fy[fy] = {
                "assets": r[assets_col],
                "liab": r[liab_col] if liab_col else None,
            }
    cash_by_fy: dict[int, object] = {}
    if cash_df is not None and not cash_df.empty and ocf_col:
        for _, r in cash_df.iterrows():
            fy = fy_of(r, fy_col_cash)
            if fy is not None:
                cash_by_fy[fy] = r[ocf_col]

    # income 行按财年降序（新→旧），最新在前
    rows = []
    for _, r in inc_df.iterrows():
        fy = fy_of(r, fy_col_inc)
        rows.append((fy if fy is not None else 0, r))
    rows.sort(key=lambda t: t[0], reverse=True)
    rows = rows[: limit]

    out: list[FinancialPeriod] = []
    n = len(rows)
    for i in range(min(periods, n)):
        fy, r = rows[i]
        revenue = _yi(r[rev_col]) if rev_col else None
        net_profit = _yi(r[ni_col]) if ni_col else None
        eps = r[eps_col] if eps_col else None
        try:
            eps = round(float(eps), 4) if eps is not None else None
        except (TypeError, ValueError):
            eps = None
        # 相邻财年（旧一年）YoY
        revenue_yoy = profit_yoy = None
        if i + 1 < n:
            _, r_prev = rows[i + 1]
            rev_prev = _yi(r_prev[rev_col]) if rev_col else None
            ni_prev = _yi(r_prev[ni_col]) if ni_col else None
            revenue_yoy = _pct((revenue - rev_prev) / rev_prev) \
                if revenue and rev_prev else None
            profit_yoy = _pct((net_profit - ni_prev) / ni_prev) \
                if net_profit and ni_prev else None
        # 毛利率 / 净利率
        cost = _yi(r[cost_col]) if cost_col else None
        gross_margin = _pct((revenue - cost) / revenue) \
            if revenue and cost is not None else None
        net_margin = _pct(net_profit / revenue) \
            if revenue and net_profit is not None else None
        # ROE：恒等式 权益 = 总资产 − 总负债（避开 common_equity 面值陷阱）
        b = bal_by_fy.get(fy, {})
        equity = None
        if b.get("assets") is not None and b.get("liab") is not None:
            try:
                equity = float(b["assets"]) - float(b["liab"])
            except (TypeError, ValueError):
                equity = None
        roe = _pct(net_profit / (_yi(equity) if equity is not None else None)) \
            if net_profit is not None and equity else None
        out.append(FinancialPeriod(
            report_date=_fmt_date(r.get("period_ending")) or "",
            revenue=revenue,
            net_profit=net_profit,
            revenue_yoy=revenue_yoy,
            profit_yoy=profit_yoy,
            roe=roe,
            gross_margin=gross_margin,
            net_margin=net_margin,
            eps=eps,
            ocf_per_share=None,  # SEC 三表无加权股数，诚实置 NULL
        ))
    return out
