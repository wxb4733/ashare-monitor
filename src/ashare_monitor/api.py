"""Python API 层（OpenBB 模式：多入口共享核心）。

CLI 命令的底层函数收拢为一致的编程接口——任何脚本 / AI Agent / MCP
一行代码即可查询数据与执行分析，无需解析命令行输出。

用法：
    import ashare_monitor.api as am

    am.quote("002594")                    # A 股行情（市场自动识别）
    am.quotes(["002594", "BTCUSDT"])      # 多市场多标的
    am.kline("NVDA")                      # 本地 K 线
    am.history("NVDA")                    # 上市以来统计
    am.profile("002594")                  # 资产画像（五维）
    am.check("600519")                    # 体检（20 维）
    am.screen("dividend", top_n=10)       # 选股
    am.backtest(["600519", "002594"])     # 组合回测
    am.factor_ic(["600519", "002594"], "momentum")   # 因子 IC 检验
    am.factor_expr("(close/Ref(close,20)-1)*100", rows)  # DSL 因子求值
    am.paper_report() / am.paper_orders() # 模拟交易账户
    am.ad_quote(["600519"])               # A 股富字段（a-stock-data）

返回类型：优先项目已有数据类（Quote/ScreenHit/CheckItem/AssetProfile），
与 CLI 同源、零重复实现。所有函数可独立 import，无副作用。
"""

from __future__ import annotations

# ── 市场识别 ─────────────────────────────────────────────────


def detect_market(code: str) -> str:
    """按代码形态识别市场：数字=A 股/港股，USDT=币，其他=美股。"""
    if not code.isdigit():
        return "crypto" if code.upper().endswith("USDT") else "us"
    return "hk" if len(code) == 5 else "ashare"


# ── 行情 / K 线 / 历史 ───────────────────────────────────────


def quote(code: str, market: str | None = None):
    """实时行情（单只，市场自动识别）。返回 Quote 或 None。"""
    from .quotes import fetch_spot_quotes

    market = market or detect_market(code)
    qs, _ = fetch_spot_quotes([code], market=market)
    return qs[0] if qs else None


def quotes(codes: list[str], market: str | None = None) -> list:
    """实时行情（多只；market=None 时按代码逐个识别）。"""
    from .quotes import fetch_spot_quotes

    if market:
        qs, _ = fetch_spot_quotes(codes, market=market)
        return qs
    out = []
    for c in codes:
        q = quote(c)
        if q:
            out.append(q)
    return out


def kline(code: str, market: str | None = None,
          days: int | None = None) -> list[dict]:
    """本地 K 线（需先 backfill）。days=None 返回全量。"""
    from .storage import load_klines

    market = market or detect_market(code)
    rows = load_klines(code, market)
    if days and len(rows) > days:
        rows = rows[-days:]
    return rows


def history(code: str, market: str | None = None) -> dict:
    """上市以来统计（年化/回撤/区间位置）。返回 dict。"""
    from .backfill import analyze_history
    from .storage import load_klines

    market = market or detect_market(code)
    rows = load_klines(code, market)
    if len(rows) < 2:
        return {"note": f"{code}({market}) 暂无入库 K 线（先 backfill）"}
    return analyze_history(rows)


# ── 画像 / 体检 ──────────────────────────────────────────────


def profile(code: str, market: str | None = None, name: str = ""):
    """资产画像（五维：市值/供给/增长/收益/估值）。返回 AssetProfile。"""
    from .asset import build_profile

    return build_profile(code, name, market or detect_market(code))


def check(code: str, market: str | None = None, name: str = "",
          cfg=None) -> list:
    """标的资料完整性体检（A 股 20 维/港股 11/美股 5/币 4）。"""
    from .check import check_stock

    return check_stock(code, name, market or detect_market(code), cfg=cfg)


# ── 选股 ─────────────────────────────────────────────────────


def screen(metric: str = "dividend", market: str = "ashare",
           top_n: int = 10, **kwargs) -> list:
    """选股器（ashare 六因子 / us 动量）。返回 list[ScreenHit]。"""
    from . import screen as _screen

    if market == "us":
        return _screen.screen_us_momentum(top_n=top_n, **kwargs)
    fn = {
        "dividend": _screen.screen_dividend,
        "sgr": _screen.screen_sgr,
        "margin": _screen.screen_margin,
        "share": _screen.screen_share,
        "lowval": _screen.screen_lowval,
        "growth": _screen.screen_growth,
    }.get(metric)
    if fn is None:
        raise ValueError(f"未知选股指标 {metric}（可选："
                         "dividend/sgr/margin/share/lowval/growth）")
    return fn(top_n=top_n, **kwargs)


# ── 策略 / 回测 / 因子 ───────────────────────────────────────


def backtest(codes: list[str], start: str | None = None,
             names: dict | None = None, **kwargs) -> dict:
    """组合回测（等权 vs 沪深 300）。返回统计 dict。"""
    from .strategy import portfolio_backtest

    return portfolio_backtest(codes, names=names, start=start, **kwargs)


def backtest_rebalanced(codes: list[str], start: str | None = None,
                        frequency: str = "monthly", cost_bps: float = 5.0,
                        limit_pct: float | None = 9.5) -> dict:
    """再平衡回测（频率/成本/涨跌停约束）。返回统计 dict。"""
    from .strategy import portfolio_backtest_rebalanced

    return portfolio_backtest_rebalanced(
        codes, start=start, frequency=frequency, cost_bps=cost_bps,
        limit_pct=limit_pct)


def factor_ic(codes: list[str], factor: str = "momentum",
              forward: int = 20) -> dict:
    """因子 IC 检验（因子名或直接表达式）。返回统计 dict。"""
    from .strategy import factor_ic_test

    return factor_ic_test(codes, factor, forward)


def factor_expr(expr: str, rows: list[dict]) -> dict:
    """DSL 因子求值（如 (close/Ref(close,20)-1)*100）。返回 {date: value}。"""
    from .factor_dsl import eval_factor_expr

    return eval_factor_expr(expr, rows)


def factor_list() -> dict:
    """全部可用因子表达式（内置 + yaml 自定义）。"""
    from .factor_dsl import load_factor_exprs

    return load_factor_exprs()


# ── 模拟交易 ─────────────────────────────────────────────────


def paper_report() -> dict:
    """模拟持仓报告（市值/盈亏/现金/净资产）。"""
    from .strategy import paper_report as _report

    return _report()


def paper_positions() -> list:
    """模拟持仓列表。"""
    from .strategy import load_paper_positions

    return load_paper_positions()


def paper_orders(limit: int = 30) -> list:
    """订单历史（状态机：New/Filled/Rejected/Canceled）。"""
    from .broker import PaperBroker

    return PaperBroker.load().orders[-limit:]


def paper_trade(targets: list, cash: float | None = None,
                commission_bps: float = 0.0,
                stamp_duty_bps: float = 0.0, dry_run: bool = False) -> dict:
    """模拟买入（整手撮合 + 现金账户 + 佣金）。返回成交/拒单。"""
    from .strategy import execute_paper_trade

    return execute_paper_trade(
        targets, dry_run=dry_run, cash=cash,
        commission_bps=commission_bps, stamp_duty_bps=stamp_duty_bps)


# ── A 股全栈富数据（a-stock-data 融合） ──────────────────────


def ad_quote(codes: list[str]) -> dict:
    """腾讯富字段行情（PE/PB/市值/换手/涨跌停）。返回 {code: {...}}。"""
    from .a_stock_data import tencent_quote_rich

    return tencent_quote_rich(codes)


def ad_hot() -> list:
    """同花顺当日强势股 + 题材归因。"""
    from .a_stock_data import ths_hot_reason

    return ths_hot_reason()


def ad_margin(code: str) -> list:
    """融资融券明细（融资余额/买入/融券）。"""
    from .a_stock_data import margin_trading

    return margin_trading(code)


def ad_lockup(code: str) -> dict:
    """限售解禁日历（历史 + 未来 90 天）。"""
    from .a_stock_data import lockup_expiry

    return lockup_expiry(code)


def ad_reports(code: str, max_pages: int = 1) -> list:
    """东财研报列表（评级/预测 EPS）。"""
    from .a_stock_data import eastmoney_reports

    return eastmoney_reports(code, max_pages=max_pages)


def ad_financial(code: str, report_type: str = "lrb") -> list:
    """新浪财报三表（fzb 资产/lrb 利润/llb 现金流）。"""
    from .a_stock_data import sina_financial_report

    return sina_financial_report(code, report_type)
