"""配置加载模块。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

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


@dataclass
class MonitorConfig:
    interval_seconds: int = 30
    trading_hours_only: bool = True
    trading_sessions: list[list[str]] = field(
        default_factory=lambda: [["09:30", "11:30"], ["13:00", "15:00"]]
    )


@dataclass
class QuoteConfig:
    # 数据源优先级，按顺序降级
    sources: list[str] = field(
        default_factory=lambda: ["sina", "tencent", "eastmoney"]
    )


@dataclass
class Config:
    watchlist: list[dict] = field(default_factory=list)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    quotes: QuoteConfig = field(default_factory=QuoteConfig)
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

    return Config(
        watchlist=raw.get("watchlist", []) or [],
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
        ),
        monitor=MonitorConfig(
            interval_seconds=int(monitor_raw.get("interval_seconds", 30)),
            trading_hours_only=bool(monitor_raw.get("trading_hours_only", True)),
            trading_sessions=monitor_raw.get(
                "trading_sessions", [["09:30", "11:30"], ["13:00", "15:00"]]
            ),
        ),
        quotes=QuoteConfig(
            sources=[str(s) for s in quotes_raw.get(
                "sources", ["sina", "tencent", "eastmoney"]
            )],
        ),
        logging=raw.get("logging", {}) or {},
    )
