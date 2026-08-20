"""配置加载模块。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = "config.yaml"


@dataclass
class AlertConfig:
    change_pct_threshold: float = 3.0
    price_above: dict[str, float] = field(default_factory=dict)
    price_below: dict[str, float] = field(default_factory=dict)
    # 盘口规则（需数据源支持五档，sina/tencent 可用；None 表示不启用）
    weibi_threshold: float | None = None       # 委比绝对值超过该百分比预警
    big_order_threshold: float | None = None   # 单档挂单量（手）超过预警
    # 波动规则：当日振幅（(最高-最低)/昨收）超过该百分比预警
    amplitude_threshold: float | None = None


@dataclass
class MonitorConfig:
    interval_seconds: int = 30
    trading_hours_only: bool = True
    trading_sessions: list[list[str]] = field(
        default_factory=lambda: [["09:30", "11:30"], ["13:00", "15:00"]]
    )
    # 监控启动时输出自选股历史波动基线
    startup_profile: bool = True
    # 预警触发时附带该股近期波动画像（按交易日缓存）
    alert_profile: bool = True
    # 画像回看交易日数
    profile_days: int = 120
    # 收盘后自动生成复盘报告
    auto_review: bool = True


@dataclass
class QuoteConfig:
    # 数据源优先级，按顺序降级
    sources: list[str] = field(
        default_factory=lambda: ["sina", "tencent", "eastmoney"]
    )


@dataclass
class ReviewConfig:
    # 复盘报告对照的大盘指数（带市场前缀，避免与个股代码冲突）
    indexes: list[str] = field(
        default_factory=lambda: ["sh000001", "sz399001", "sz399006"]
    )
    # 报告内 K 线回看交易日数
    kline_days: int = 60


@dataclass
class ScanConfig:
    # 每个榜单展示条数
    limit: int = 10
    # 剔除 ST / 低价股
    exclude_st: bool = True
    min_price: float = 2.0
    # 放量异动量比阈值
    volume_ratio: float = 2.0
    # 高换手阈值（%）
    turnover_rate: float = 5.0


@dataclass
class SignalConfig:
    # 量能信号阈值
    volume_ratio_high: float = 1.2
    volume_ratio_low: float = 0.8
    # 动量回看周期与强弱阈值（%）
    momentum_window: int = 20
    momentum_pct: float = 3.0


@dataclass
class ObsidianConfig:
    # Obsidian 库根目录（留空禁用复盘 Markdown 导出）。
    # 支持相对路径：相对 config 文件所在目录解析（默认项目内 obsidian-vault/）
    vault: str = "obsidian-vault"
    # 库内复盘报告子目录
    reports_dir: str = "A股复盘"


@dataclass
class Config:
    watchlist: list[dict] = field(default_factory=list)
    positions: list[dict] = field(default_factory=list)  # 持仓：code/name/market/cost/shares
    alerts: AlertConfig = field(default_factory=AlertConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    quotes: QuoteConfig = field(default_factory=QuoteConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    signals: SignalConfig = field(default_factory=SignalConfig)
    obsidian: ObsidianConfig = field(default_factory=ObsidianConfig)
    logging: dict = field(default_factory=dict)


def load_config(path: str | None = None) -> Config:
    """从 YAML 文件加载配置。优先使用 config.local.yaml（已被 gitignore）。"""
    path = path or DEFAULT_CONFIG_PATH
    local_path = path.replace(".yaml", ".local.yaml")
    if os.path.exists(local_path):
        path = local_path
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    alerts_raw = raw.get("alerts", {}) or {}
    monitor_raw = raw.get("monitor", {}) or {}
    quotes_raw = raw.get("quotes", {}) or {}
    review_raw = raw.get("review", {}) or {}
    scan_raw = raw.get("scan", {}) or {}
    signals_raw = raw.get("signals", {}) or {}
    obsidian_raw = raw.get("obsidian", {}) or {}

    return Config(
        watchlist=raw.get("watchlist", []) or [],
        positions=raw.get("positions", []) or [],
        alerts=AlertConfig(
            change_pct_threshold=float(alerts_raw.get("change_pct_threshold", 3.0)),
            price_above={str(k): float(v) for k, v in (alerts_raw.get("price_above") or {}).items()},
            price_below={str(k): float(v) for k, v in (alerts_raw.get("price_below") or {}).items()},
            weibi_threshold=(
                float(alerts_raw["weibi_threshold"])
                if alerts_raw.get("weibi_threshold") is not None else None
            ),
            big_order_threshold=(
                float(alerts_raw["big_order_threshold"])
                if alerts_raw.get("big_order_threshold") is not None else None
            ),
            amplitude_threshold=(
                float(alerts_raw["amplitude_threshold"])
                if alerts_raw.get("amplitude_threshold") is not None else None
            ),
        ),
        monitor=MonitorConfig(
            interval_seconds=int(monitor_raw.get("interval_seconds", 30)),
            trading_hours_only=bool(monitor_raw.get("trading_hours_only", True)),
            trading_sessions=monitor_raw.get(
                "trading_sessions", [["09:30", "11:30"], ["13:00", "15:00"]]
            ),
            startup_profile=bool(monitor_raw.get("startup_profile", True)),
            alert_profile=bool(monitor_raw.get("alert_profile", True)),
            profile_days=int(monitor_raw.get("profile_days", 120)),
            auto_review=bool(monitor_raw.get("auto_review", True)),
        ),
        quotes=QuoteConfig(
            sources=[str(s) for s in quotes_raw.get(
                "sources", ["sina", "tencent", "eastmoney"]
            )],
        ),
        review=ReviewConfig(
            indexes=[str(s) for s in review_raw.get(
                "indexes", ["sh000001", "sz399001", "sz399006"]
            )],
            kline_days=int(review_raw.get("kline_days", 60)),
        ),
        scan=ScanConfig(
            limit=int(scan_raw.get("limit", 10)),
            exclude_st=bool(scan_raw.get("exclude_st", True)),
            min_price=float(scan_raw.get("min_price", 2.0)),
            volume_ratio=float(scan_raw.get("volume_ratio", 2.0)),
            turnover_rate=float(scan_raw.get("turnover_rate", 5.0)),
        ),
        signals=SignalConfig(
            volume_ratio_high=float(signals_raw.get("volume_ratio_high", 1.2)),
            volume_ratio_low=float(signals_raw.get("volume_ratio_low", 0.8)),
            momentum_window=int(signals_raw.get("momentum_window", 20)),
            momentum_pct=float(signals_raw.get("momentum_pct", 3.0)),
        ),
        obsidian=ObsidianConfig(
            vault=_resolve_vault(str(obsidian_raw.get("vault", "obsidian-vault")), path),
            reports_dir=str(obsidian_raw.get("reports_dir", "A股复盘")),
        ),
        logging=raw.get("logging", {}) or {},
    )


def _resolve_vault(vault: str, config_path: str) -> str:
    """vault 相对路径 → 相对 config 文件所在目录解析为绝对路径。"""
    if not vault.strip():
        return ""
    p = Path(vault)
    if p.is_absolute():
        return str(p)
    return str((Path(config_path).resolve().parent / p).resolve())
