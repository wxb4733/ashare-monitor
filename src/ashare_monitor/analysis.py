"""历史数据分析：拉取个股日线历史并计算波动与趋势指标。

数据来源：优先 akshare 东方财富历史行情（stock_zh_a_hist）；
失败时降级腾讯 K 线接口（web.ifzq.gtimg.cn，思路借鉴 easyquotation.daykline）。
所有指标计算函数均接受 DataFrame 输入，与网络请求解耦，便于测试。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

# A 股年交易日数（近似）
TRADING_DAYS_PER_YEAR = 250


@dataclass
class HistoryReport:
    code: str
    name: str
    start_date: str
    end_date: str
    bars: int                      # K 线根数
    latest_close: float
    period_return_pct: float       # 区间涨跌幅 %
    annual_volatility_pct: float   # 年化波动率 %
    recent20_volatility_pct: float # 近 20 日年化波动率 %
    max_drawdown_pct: float        # 最大回撤 %（负数）
    avg_amplitude_pct: float       # 平均日振幅 %
    up_days: int
    down_days: int
    ma: dict[int, float] = field(default_factory=dict)   # 均线 {周期: 值}
    volume_ma5: float = 0.0        # 近 5 日均量（手）
    volume_ma20: float = 0.0       # 近 20 日均量（手）
    daily_returns: pd.Series | None = None  # 日收益率序列（备查/画图）

    @property
    def volume_ratio(self) -> float | None:
        """量比近似：近 5 日均量 / 近 20 日均量。"""
        if self.volume_ma20 == 0:
            return None
        return self.volume_ma5 / self.volume_ma20

    @property
    def win_rate(self) -> float:
        """上涨交易日占比 %。"""
        total = self.up_days + self.down_days
        return self.up_days / total * 100 if total else 0.0


def fetch_history(
    code: str,
    days: int = 250,
    adjust: str = "qfq",
    market: str = "ashare",
    period: str = "daily",
) -> tuple[pd.DataFrame, str]:
    """拉取标的的历史 K 线。

    :param code: 证券代码（A 股 6 位 / 港股 5 位 / 币安交易对）
    :param days: 返回最近 N 根 K 线
    :param adjust: 复权方式 qfq/hfq/空字符串（仅 A 股/港股有效）
    :param market: ashare / hk / crypto
    :param period: daily / weekly / monthly
    :return: (DataFrame, 股票名称)
    """
    if market == "crypto":
        return _fetch_history_binance(code, days, period), code.upper()
    if market == "hk":
        df = _fetch_history_tencent_hk(code, days, adjust, period)
        return df.tail(days).reset_index(drop=True), _lookup_hk_name(code)
    # 指数代码（sh/sz/bj 前缀）直连腾讯，不依赖 akshare
    if code[:2].lower() in ("sh", "sz", "bj", "zz"):
        df = _fetch_history_tencent(code, days, adjust, period)
        return df.tail(days).reset_index(drop=True), _lookup_name(code)
    try:
        return _fetch_history_akshare(code, days, adjust, period)
    except Exception as exc:  # noqa: BLE001 - 单源失败自动降级
        logger.warning("akshare 历史数据拉取失败，降级腾讯 K 线: %s", exc)
        df = _fetch_history_tencent(code, days, adjust, period)
        return df.tail(days).reset_index(drop=True), _lookup_name(code)


# 周期 → 腾讯接口 period 参数 / akshare period / 币安 interval / 年化周期数
_PERIOD_MAP = {
    "daily": {"tencent": "day", "akshare": "daily", "binance": "1d", "per_year": 250},
    "weekly": {"tencent": "week", "akshare": "weekly", "binance": "1w", "per_year": 52},
    "monthly": {"tencent": "month", "akshare": "monthly", "binance": "1M", "per_year": 12},
}


def periods_per_year_for(period: str, market: str = "ashare") -> int:
    """年化周期数：日线 250（crypto 365）、周线 52、月线 12。"""
    if period == "daily" and market == "crypto":
        return 365
    return _PERIOD_MAP.get(period, _PERIOD_MAP["daily"])["per_year"]


def _fetch_history_tencent_hk(code: str, days: int, adjust: str,
                              period: str = "daily") -> pd.DataFrame:
    """腾讯港股 K 线接口（思路借鉴 easyquotation.daykline，MIT License）。

    GET https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param=hk00700,day,,,320,qfq
    """
    import requests

    symbol = f"hk{code[-5:]}"
    n = min(days + 10, 800)
    tencent_period = _PERIOD_MAP.get(period, _PERIOD_MAP["daily"])["tencent"]
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
        f"?param={symbol},{tencent_period},,,{n},{adjust}"
    )
    resp = requests.get(url, timeout=10, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    })
    resp.raise_for_status()
    return _parse_tencent_kline(resp.json(), symbol, code, period)


def _fetch_history_binance(code: str, days: int, period: str = "daily") -> pd.DataFrame:
    """币安 K 线（klines）。"""
    from .providers.binance import fetch_klines

    interval = _PERIOD_MAP.get(period, _PERIOD_MAP["daily"])["binance"]
    rows = fetch_klines(code, days, interval=interval)
    if not rows:
        raise RuntimeError(f"币安未返回 {code} 的 K 线数据")
    df = pd.DataFrame(
        [
            (
                datetime.fromtimestamp(int(r[0]) / 1000).strftime("%Y-%m-%d"),
                float(r[1]),   # 开
                float(r[4]),   # 收
                float(r[2]),   # 高
                float(r[3]),   # 低
                float(r[5]),   # 成交量（基础币）
            )
            for r in rows
        ],
        columns=["日期", "开盘", "收盘", "最高", "最低", "成交量"],
    )
    prev_close = df["收盘"].shift(1)
    df["涨跌幅"] = (df["收盘"] / prev_close - 1) * 100
    df["振幅"] = (df["最高"] - df["最低"]) / prev_close * 100
    df.loc[df.index[0], ["涨跌幅", "振幅"]] = 0.0
    return df


def _lookup_hk_name(code: str) -> str:
    """通过腾讯港股行情接口补全名称（失败返回空）。"""
    try:
        from .providers.hk import TencentHKProvider

        quotes = TencentHKProvider().fetch([code])
        return quotes[0].name if quotes else ""
    except Exception:  # noqa: BLE001
        return ""


def _fetch_history_akshare(
    code: str, days: int, adjust: str, period: str = "daily"
) -> tuple[pd.DataFrame, str]:
    try:
        import akshare as ak
    except ImportError as exc:  # akshare 为可选依赖，缺失走腾讯直连
        raise RuntimeError(f"akshare 未安装（可选依赖），改用直连数据源: {exc}")

    end = datetime.now()
    # 按交易日约为自然日 0.7 倍估算，多取余量（周线/月线取整倍数更宽裕）
    scale = {"daily": 0.7, "weekly": 5, "monthly": 22}.get(period, 0.7)
    start = end - timedelta(days=int(days / scale) + 20)
    df: pd.DataFrame = ak.stock_zh_a_hist(
        symbol=code[-6:],
        period=_PERIOD_MAP.get(period, _PERIOD_MAP["daily"])["akshare"],
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust=adjust,
    )
    if df.empty:
        raise RuntimeError(f"未获取到 {code} 的历史数据")

    name = ""
    try:
        name = str(df["名称"].iloc[-1]) if "名称" in df.columns else ""
    except Exception:  # noqa: BLE001
        pass
    return df.tail(days).reset_index(drop=True), name


def _fetch_history_tencent(code: str, days: int, adjust: str,
                           period: str = "daily") -> pd.DataFrame:
    """腾讯 K 线接口（思路借鉴 easyquotation.daykline，MIT License）。

    GET https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,,,320,qfq
    返回 qfqday/hfqday/day 键下的 [日期, 开, 收, 高, 低, 成交量(手)] 列表。
    """
    import requests

    from .providers.base import get_market_prefix

    symbol = get_market_prefix(code) + code[-6:]
    n = min(days + 10, 800)  # 接口单次上限约 800 根
    tencent_period = _PERIOD_MAP.get(period, _PERIOD_MAP["daily"])["tencent"]
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={symbol},{tencent_period},,,{n},{adjust}"
    )
    resp = requests.get(url, timeout=10, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    })
    resp.raise_for_status()
    return _parse_tencent_kline(resp.json(), symbol, code, period)


def _parse_tencent_kline(payload: dict, symbol: str, code: str,
                         period: str = "daily") -> pd.DataFrame:
    """解析腾讯 K 线 JSON 为 akshare 风格 DataFrame（独立出来便于测试）。"""
    node = payload.get("data", {}).get(symbol)
    if not node:
        raise RuntimeError(f"腾讯 K 线接口未返回 {code} 数据")
    suffix = _PERIOD_MAP.get(period, _PERIOD_MAP["daily"])["tencent"]
    rows = next((v for k, v in node.items() if k.endswith(suffix) and v), None)
    if not rows:
        raise RuntimeError(f"腾讯 K 线接口 {code} 无{suffix} K 数据")

    df = pd.DataFrame(
        [(r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
         for r in rows],
        columns=["日期", "开盘", "收盘", "最高", "最低", "成交量"],
    )
    prev_close = df["收盘"].shift(1)
    df["涨跌幅"] = (df["收盘"] / prev_close - 1) * 100
    df["振幅"] = (df["最高"] - df["最低"]) / prev_close * 100
    df.loc[df.index[0], ["涨跌幅", "振幅"]] = 0.0
    return df


def _lookup_name(code: str) -> str:
    """通过腾讯实时行情接口补全股票名称（失败则返回空）。"""
    try:
        from .providers.tencent import TencentProvider

        quotes = TencentProvider().fetch([code])
        return quotes[0].name if quotes else ""
    except Exception:  # noqa: BLE001
        return ""


def compute_metrics(df: pd.DataFrame, code: str = "", name: str = "",
                    periods_per_year: int = TRADING_DAYS_PER_YEAR) -> HistoryReport:
    """基于日线 DataFrame 计算波动与趋势指标。

    需要列：日期、开盘、收盘、最高、最低、成交量、涨跌幅、振幅（akshare 格式）。
    periods_per_year：年化因子（A 股/港股约 250 个交易日，加密货币 365）。
    """
    close = df["收盘"].astype(float)
    returns = close.pct_change().dropna()

    # 区间涨跌幅（以首根开盘为基准更贴近"持有至今"）
    period_return = (close.iloc[-1] / close.iloc[0] - 1) * 100

    # 年化波动率：日收益标准差 × √年周期数
    annual_vol = returns.std() * math.sqrt(periods_per_year) * 100 if len(returns) > 1 else 0.0
    recent20 = returns.tail(20)
    recent20_vol = (
        recent20.std() * math.sqrt(periods_per_year) * 100
        if len(recent20) > 1 else 0.0
    )

    # 最大回撤：基于收盘价累计净值
    nav = close / close.iloc[0]
    drawdown = nav / nav.cummax() - 1
    max_dd = drawdown.min() * 100

    # 平均振幅：优先用数据自带的振幅列，否则按 (高-低)/昨收 计算
    if "振幅" in df.columns:
        avg_amp = float(df["振幅"].astype(float).mean())
    else:
        prev_close = close.shift(1)
        amp = (df["最高"].astype(float) - df["最低"].astype(float)) / prev_close * 100
        avg_amp = float(amp.dropna().mean())

    # 涨跌天数
    chg = df["涨跌幅"].astype(float) if "涨跌幅" in df.columns else returns.reindex(df.index).fillna(0)
    up_days = int((chg > 0).sum())
    down_days = int((chg < 0).sum())

    # 均线
    ma = {
        n: float(close.rolling(n).mean().iloc[-1])
        for n in (5, 10, 20, 60)
        if len(close) >= n
    }

    # 量能（成交量单位：手）
    volume = df["成交量"].astype(float)
    volume_ma5 = float(volume.tail(5).mean())
    volume_ma20 = float(volume.tail(20).mean())

    return HistoryReport(
        code=code,
        name=name,
        start_date=str(df["日期"].iloc[0])[:10],
        end_date=str(df["日期"].iloc[-1])[:10],
        bars=len(df),
        latest_close=float(close.iloc[-1]),
        period_return_pct=round(period_return, 2),
        annual_volatility_pct=round(annual_vol, 2),
        recent20_volatility_pct=round(recent20_vol, 2),
        max_drawdown_pct=round(max_dd, 2),
        avg_amplitude_pct=round(avg_amp, 2),
        up_days=up_days,
        down_days=down_days,
        ma=ma,
        volume_ma5=volume_ma5,
        volume_ma20=volume_ma20,
        daily_returns=returns,
    )


def analyze(code: str, days: int = 250, adjust: str = "qfq",
            market: str = "ashare", period: str = "daily") -> HistoryReport:
    """拉取历史数据并计算指标（网络 + 计算的组合入口）。

    加密货币按 365 天年化，股票按 250 个交易日年化；周线 52、月线 12。
    """
    df, name = fetch_history(code, days=days, adjust=adjust, market=market,
                             period=period)
    periods = periods_per_year_for(period, market)
    return compute_metrics(df, code=code, name=name, periods_per_year=periods)


def brief_profile(report: HistoryReport) -> str:
    """把分析报告压缩成一行画像，供监控预警附带展示。"""
    parts = [
        f"近{report.bars}日 {report.period_return_pct:+.1f}%",
        f"年化波动 {report.annual_volatility_pct:.1f}%",
        f"近20日波动 {report.recent20_volatility_pct:.1f}%",
        f"最大回撤 {report.max_drawdown_pct:.1f}%",
        f"日均振幅 {report.avg_amplitude_pct:.1f}%",
    ]
    if report.ma.get(20):
        pos = "上方" if report.latest_close >= report.ma[20] else "下方"
        parts.append(f"MA20{pos}")
    vol_ratio = report.volume_ratio
    if vol_ratio is not None:
        parts.append(f"量比 {vol_ratio:.2f}")
    return " | ".join(parts)


class ProfileCache:
    """波动画像按交易日缓存：每个标的每天只拉取一次历史数据。

    监控轮询间隔以秒计，而历史画像在单个交易日内基本不变，
    缓存避免预警密集时反复请求拖慢轮询。
    """

    def __init__(self, days: int = 120):
        self.days = days
        self._cache: dict[tuple[str, str], tuple[str, str]] = {}  # (market, code) -> (日期, 画像)

    def get(self, code: str, market: str = "ashare") -> str | None:
        """返回该标的当日画像（波动 + 技术指标）；失败返回 None 不阻塞监控。"""
        today = datetime.now().strftime("%Y-%m-%d")
        key = (market, code)
        cached = self._cache.get(key)
        if cached and cached[0] == today:
            return cached[1]
        try:
            from .indicators import compute_indicators

            adjust = "qfq" if market != "crypto" else ""
            df, _name = fetch_history(code, days=self.days, adjust=adjust, market=market)
            periods = 365 if market == "crypto" else TRADING_DAYS_PER_YEAR
            report = compute_metrics(df, code=code, periods_per_year=periods)
            ind = compute_indicators(df)
            profile = f"{brief_profile(report)} | {ind.summary_line()}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("波动画像拉取失败 %s(%s): %s", code, market, exc)
            return None
        self._cache[key] = (today, profile)
        return profile
