"""全市场异动扫描：从自选股盯盘升级到全市场发现。

数据来源（自动降级）：
1. 东方财富全市场快照（akshare stock_zh_a_spot_em）：字段最全，
   含换手率 / 量比；
2. 新浪全市场快照（失败时降级）：仅有基础行情，
   放量榜 / 换手榜不可用（字段缺失），代码表来自 easyquotation
   （MIT License，Copyright (c) 2018 shidenggui）。

输出各榜单：涨幅榜 / 跌幅榜 / 放量异动榜 / 换手榜 / 振幅榜。
所有榜单计算函数接受 DataFrame 输入，与网络请求解耦，便于测试。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_STOCK_CODES_PATH = Path(__file__).parent / "data" / "stock_codes.conf"
_SINA_BATCH = 800  # 新浪单次请求最大代码数

# 东财快照列名 → 内部名
_COL = {
    "code": "代码",
    "name": "名称",
    "price": "最新价",
    "change_pct": "涨跌幅",
    "turnover_rate": "换手率",
    "volume_ratio": "量比",
    "amplitude": "振幅",
    "amount": "成交额",
}


@dataclass
class ScanConfig:
    limit: int = 10          # 每个榜单展示条数
    exclude_st: bool = True  # 剔除 ST
    min_price: float = 2.0   # 剔除仙股/低价股
    volume_ratio: float = 2.0   # 放量异动量比阈值
    turnover_rate: float = 5.0  # 高换手阈值（%）


@dataclass
class ScanResult:
    gainers: list[dict] = field(default_factory=list)    # 涨幅榜
    losers: list[dict] = field(default_factory=list)     # 跌幅榜
    volume_spikes: list[dict] = field(default_factory=list)  # 放量异动
    hot_turnover: list[dict] = field(default_factory=list)   # 高换手
    wide_amplitude: list[dict] = field(default_factory=list) # 高振幅


def fetch_market_snapshot() -> pd.DataFrame:
    """拉取 A 股全市场实时快照。

    优先东财（字段全），失败自动降级新浪（基础字段）。
    """
    try:
        return _fetch_eastmoney_snapshot()
    except Exception as exc:  # noqa: BLE001
        logger.warning("东财全市场快照失败，降级新浪: %s", exc)
        return _fetch_sina_snapshot()


def _fetch_eastmoney_snapshot() -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(f"akshare 未安装（可选依赖）: {exc}")

    df = ak.stock_zh_a_spot_em()
    df["代码"] = df["代码"].astype(str).str[-6:]
    return df


def _load_stock_codes() -> list[str]:
    with open(_STOCK_CODES_PATH, encoding="utf-8") as f:
        return json.load(f)["stock"]


def _snapshot_from_quotes(quotes) -> pd.DataFrame:
    """把新浪行情 Quote 列表转换为快照 DataFrame（独立出来便于测试）。

    新浪源缺少换手率 / 量比字段，对应列置 None。
    """
    from .quotes import Quote

    rows = []
    for q in quotes:
        if not isinstance(q, Quote):
            continue
        rows.append({
            "代码": q.code,
            "名称": q.name,
            "最新价": q.price,
            "涨跌幅": q.change_pct,
            "换手率": None,
            "量比": None,
            "振幅": q.amplitude if q.amplitude is not None else 0.0,
            "成交额": q.turnover,
        })
    if not rows:
        raise RuntimeError("新浪全市场快照未返回数据")
    return pd.DataFrame(rows)


def _fetch_sina_snapshot() -> pd.DataFrame:
    """新浪全市场快照：按代码表分批请求，拼成快照 DataFrame。"""
    from .providers.sina import SinaProvider

    codes = _load_stock_codes()
    provider = SinaProvider()
    quotes = []
    for i in range(0, len(codes), _SINA_BATCH):
        batch = codes[i:i + _SINA_BATCH]
        quotes.extend(provider.fetch(batch))
        logger.debug("新浪快照已拉取 %d/%d", min(i + _SINA_BATCH, len(codes)), len(codes))
    return _snapshot_from_quotes(quotes)


def _clean(df: pd.DataFrame, cfg: ScanConfig) -> pd.DataFrame:
    """按配置过滤：剔除 ST / 停牌 / 低价。"""
    d = df.copy()
    d["涨跌幅"] = pd.to_numeric(d["涨跌幅"], errors="coerce")
    d["最新价"] = pd.to_numeric(d["最新价"], errors="coerce")
    d["换手率"] = pd.to_numeric(d["换手率"], errors="coerce")
    d["量比"] = pd.to_numeric(d["量比"], errors="coerce")
    d["振幅"] = pd.to_numeric(d["振幅"], errors="coerce")
    d["成交额"] = pd.to_numeric(d["成交额"], errors="coerce")
    d = d.dropna(subset=["最新价", "涨跌幅"])
    if cfg.exclude_st:
        d = d[~d["名称"].str.contains("ST", case=False, na=False)]
    d = d[d["最新价"] >= cfg.min_price]
    # 剔除停牌（涨跌幅为 0 且无成交）
    d = d[~((d["涨跌幅"] == 0) & (d["成交额"].fillna(0) == 0))]
    return d


def _row(r: pd.Series) -> dict:
    return {
        "code": r["代码"],
        "name": r["名称"],
        "price": float(r["最新价"]),
        "change_pct": float(r["涨跌幅"]),
        "turnover_rate": _safe(r.get("换手率")),
        "volume_ratio": _safe(r.get("量比")),
        "amplitude": _safe(r.get("振幅")),
        "amount": _safe(r.get("成交额")),
    }


def _safe(v) -> float | None:
    try:
        if pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def scan_market(df: pd.DataFrame | None = None, cfg: ScanConfig | None = None) -> ScanResult:
    """对全市场快照执行异动扫描。

    :param df: 全市场快照（akshare 格式），None 则实时拉取
    :param cfg: 扫描配置
    """
    cfg = cfg or ScanConfig()
    if df is None:
        df = fetch_market_snapshot()
    d = _clean(df, cfg)

    result = ScanResult(
        gainers=[_row(r) for _, r in d.nlargest(cfg.limit, "涨跌幅").iterrows()],
        losers=[_row(r) for _, r in d.nsmallest(cfg.limit, "涨跌幅").iterrows()],
        volume_spikes=[
            _row(r) for _, r in d[d["量比"] >= cfg.volume_ratio]
            .nlargest(cfg.limit, "量比").iterrows()
        ],
        hot_turnover=[
            _row(r) for _, r in d[d["换手率"] >= cfg.turnover_rate]
            .nlargest(cfg.limit, "换手率").iterrows()
        ],
        wide_amplitude=[
            _row(r) for _, r in d.nlargest(cfg.limit, "振幅").iterrows()
        ],
    )
    return result
