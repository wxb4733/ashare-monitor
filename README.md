# ashare-monitor

A 股交易信息监控工具：实时行情快照、涨跌幅预警、价格突破提醒。

## 功能

- **实时行情**：基于 akshare 获取自选股实时快照（最新价、涨跌幅、成交量、成交额等）
- **预警规则**：涨跌幅超阈值、价格上破 / 下破指定价位，内置冷却去抖避免重复告警
- **交易时段控制**：默认仅在 09:30–11:30 / 13:00–15:00 轮询
- **通知渠道**：控制台彩色输出（涨红跌绿），支持 webhook（企业微信 / 钉钉机器人）

## 快速开始

```bash
# 创建虚拟环境并安装
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"   # Windows
# .venv/bin/pip install -e ".[dev]"     # Linux/macOS

# 编辑自选股与预警规则
vim config.yaml

# 单次行情快照
python -m ashare_monitor.main once

# 持续监控
python -m ashare_monitor.main monitor
```

安装为命令后也可直接使用 `ashare-monitor once` / `ashare-monitor monitor`。

## 配置说明（config.yaml）

| 配置项 | 说明 |
| --- | --- |
| `watchlist` | 自选股列表，6 位代码 |
| `alerts.change_pct_threshold` | 涨跌幅预警阈值（%），默认 ±3% |
| `alerts.price_above / price_below` | 按代码设置价格上破 / 下破提醒 |
| `monitor.interval_seconds` | 轮询间隔，默认 30s |
| `monitor.trading_hours_only` | 是否仅在交易时段运行 |

如需本地私有配置，复制为 `config.local.yaml`（已被 gitignore）。

## Webhook 通知

设置环境变量 `ASHARE_MONITOR_WEBHOOK` 为企业微信 / 钉钉机器人地址，预警会同时推送到 webhook。

## 运行测试

```bash
pytest
```

## 免责声明

本项目仅供学习与技术研究，行情数据来源于公开接口，不构成任何投资建议。
