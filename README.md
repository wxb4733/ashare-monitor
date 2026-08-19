# ashare-monitor

多市场（A 股 / 港股 / 加密货币）交易信息监控工具：实时行情快照、涨跌幅预警、价格突破提醒。

## 功能

- **多市场支持**：A 股（默认）、港股（`market: hk`）、币安加密货币（`market: crypto`，7×24）
- **实时行情**：多数据源自动降级（新浪 → 腾讯 → 东方财富），单一接口故障不影响监控
- **五档盘口**：买一~买五 / 卖一~卖五挂单明细与委比计算（sina / tencent 源，A 股）
- **预警规则**：涨跌幅超阈值、价格上破 / 下破、委比失衡、单档大单挂单、振幅波动，内置冷却去抖避免重复告警
- **分市场交易时段**：A 股 09:30–11:30/13:00–15:00，港股 09:30–12:00/13:00–16:00，加密货币 7×24
- **通知渠道**：控制台彩色输出（涨红跌绿），支持 webhook（企业微信 / 钉钉机器人）

## 数据源

| 数据源 | 市场 | 特点 | 说明 |
| --- | --- | --- | --- |
| `sina` | A 股 | 按需查询、速度快 | 新浪行情网关，适合盘中高频轮询 |
| `tencent` | A 股 | 按需查询、更新频率高 | 腾讯行情网关 |
| `tencent_hk` | 港股 | 按需查询 | 腾讯港股行情（借鉴 easyquotation.hkquote） |
| `eastmoney` | A 股 | 字段最全 | 基于 akshare 全市场快照，开销较大，作为兜底 |
| `binance` | 加密货币 | 公开 REST API | 无需 Key，主备域名自动切换 |

在 `config.yaml` 的 `quotes.sources` 中配置 A 股优先级，按顺序降级，首个可用的生效。

新浪 / 腾讯（含港股）源的解析逻辑借鉴自 [easyquotation](https://github.com/shidenggui/easyquotation)
（MIT License，Copyright (c) 2018 shidenggui），特此致谢。

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

# 历史数据分析（近 120 个交易日，前复权）
python -m ashare_monitor.main analyze 600519 --days 120 --adjust qfq

# 港股 / 加密货币分析
python -m ashare_monitor.main analyze 00700 --market hk --days 60
python -m ashare_monitor.main analyze BTCUSDT --market crypto --days 60

# 规则化交易信号（结合实时行情；仅供参考，不构成投资建议）
python -m ashare_monitor.main advice 600519 --days 120
python -m ashare_monitor.main advice BTCUSDT --market crypto --days 60

# 技术指标监控（MACD/RSI/KDJ/BOLL）
python -m ashare_monitor.main indicator 600519 --days 120
python -m ashare_monitor.main indicator BTCUSDT --market crypto --days 60

# 生成复盘报告（默认今天，可指定日期）
python -m ashare_monitor.main review [--date 2026-08-18]

# 全市场异动扫描（涨幅/跌幅/放量/换手/振幅榜）
python -m ashare_monitor.main scan

# 周/月复盘汇总报告（基于 SQLite 积累的数据）
python -m ashare_monitor.main report --weekly
python -m ashare_monitor.main report --monthly
```

安装为命令后也可直接使用 `ashare-monitor once` / `ashare-monitor monitor` / `ashare-monitor analyze` / `ashare-monitor advice` / `ashare-monitor indicator` / `ashare-monitor review` / `ashare-monitor scan` / `ashare-monitor report`。

## 技术指标监控（indicator）

`indicator` 命令输出四类指标（纯 pandas 实现，无 TA-Lib 依赖）：

- **MACD(12,26,9)**：DIF/DEA/柱，金叉/死叉状态、最近交叉日期与距今天数
- **RSI(14)**：含 6/24 日多周期值，超买（≥70）/ 超卖（≤30）判定
- **KDJ(9,3,3)**：K/D/J 值，金叉/死叉与超买超卖
- **BOLL(20,2)**：上中下轨、现价位置（超上轨/中上/中下/超下轨）、带宽

`advice` 命令同样附带指标板块；**监控预警的波动画像中也自动带上指标摘要**
（如 `MACD死叉(2日前) | RSI 48 | KDJ死叉 | BOLL中下`），实现"指标状态入预警"。

## 交易信号（advice）

`advice` 命令结合**实时行情 + 历史分析**，输出规则化信号：

- **均线信号**：MA5/10/20 多空排列、现价相对 MA20/MA60 位置
- **量能信号**：量比放量 / 缩量（`signals.volume_ratio_high/low` 配置）
- **波动信号**：近 20 日波动相对年化放大（风险上升）/ 收窄（临近变盘）
- **动量信号**：近 N 日累计涨跌（`signals.momentum_window/pct` 配置）

每条信号带方向与得分，最后给出综合研判（偏多/中性/偏空 + 信号一致度）。
`analyze` 报告同样附带信号板块。

> **重要提示**：本模块输出为规则化参考信号，**不构成投资建议**。所有输出均附完整免责声明，
> 交易决策请结合个人风险承受能力独立判断。

## 全市场异动扫描（scan）

从自选股盯盘升级到全市场发现，输出五个榜单：**涨幅榜 / 跌幅榜 / 放量异动（量比≥阈值）/ 高换手 / 高振幅**。

- 数据源：优先东财全市场快照（字段全，含量比/换手率），失败自动降级新浪（仅基础字段，放量/换手榜不可用）
- 默认剔除 ST 与低价股（`scan.exclude_st` / `scan.min_price` 配置）

## 历史复盘数据积累（SQLite + report）

- 监控期间预警双写：JSONL 审计日志 + **SQLite**（`data/ashore_monitor.db`），支持按日期/规则/标的聚合查询
- 每日复盘报告生成后自动入库（行情摘要、预警统计）
- `report --weekly/--monthly` 输出汇总报告：区间行情表现、预警规则分布 / 每日预警数 / 标的排行（ECharts 柱状图）、每日复盘记录、预警明细

## 收盘复盘报告（review）

监控运行期间，触发的预警实时落盘到 `logs/alerts/alerts-YYYY-MM-DD.jsonl`；
收盘后（15:00 后）自动生成 HTML 复盘报告到 `output/review-YYYY-MM-DD.html`，包含：

- **大盘指数对照**：上证 / 深成 / 创业板当日点位、涨跌幅与近 60 日 K 线
- **技术指标状态**：每只自选股当日 MACD / RSI / KDJ / BOLL 一览
- **自选股当日表现**：收盘、涨跌幅、振幅、量能
- **预警时间线**：全天触发的预警（含各股波动画像）
- **近期 K 线**：每只自选股近 60 日蜡烛图 + 成交量（ECharts，涨红跌绿），图题标注波动画像与指标摘要

`monitor.auto_review: false` 可关闭自动生成，随时可用 `review` 命令手动补生成。
若配置了 `ASHARE_MONITOR_WEBHOOK`，报告生成后会自动推送一条复盘摘要到 webhook。
指数列表与 K 线天数在 `review.indexes` / `review.kline_days` 配置。

## 历史数据分析（analyze）

拉取个股日线历史（优先东财 akshare，失败自动降级腾讯 K 线），输出：

- **概览**：最新收盘、区间涨跌幅、上涨/下跌天数与胜率
- **波动指标**：年化波动率、近 20 日波动率、最大回撤、平均日振幅
- **趋势**：MA5/10/20/60 与收盘价相对位置
- **量能**：近 5 日 / 20 日均量与量比

分析能力已接入监控流程：监控启动时输出自选股波动基线表；预警触发时自动附带
该股一行波动画像（近 N 日涨跌 / 年化波动 / 最大回撤 / 日均振幅 / MA20 位置 / 量比），
按交易日缓存，每只股票每天只拉取一次历史数据，不影响轮询性能。

## 配置说明（config.yaml）

| 配置项 | 说明 |
| --- | --- |
| `watchlist` | 自选标的列表，每项 `code` + 可选 `market`（ashare 默认 / hk / crypto） |
| `alerts.change_pct_threshold` | 涨跌幅预警阈值（%），默认 ±3% |
| `alerts.price_above / price_below` | 按代码设置价格上破 / 下破提醒 |
| `alerts.weibi_threshold` | 委比绝对值超阈值预警（%），需五档数据，不设则关闭 |
| `alerts.big_order_threshold` | 单档挂单量（手）超阈值预警，不设则关闭 |
| `alerts.amplitude_threshold` | 当日振幅（%）超阈值波动预警，不设则关闭 |
| `monitor.interval_seconds` | 轮询间隔，默认 30s |
| `monitor.trading_hours_only` | 是否仅在交易时段运行 |
| `monitor.startup_profile` | 启动时输出自选股历史波动基线，默认开 |
| `monitor.alert_profile` | 预警触发时附带该股近期波动画像（按交易日缓存），默认开 |
| `monitor.profile_days` | 画像回看交易日数，默认 120 |
| `quotes.sources` | 行情数据源及优先级，默认 `["sina", "tencent", "eastmoney"]` |

如需本地私有配置，复制为 `config.local.yaml`（已被 gitignore）。

## Webhook 通知

设置环境变量 `ASHARE_MONITOR_WEBHOOK` 为企业微信 / 钉钉机器人地址，预警会同时推送到 webhook。

## 运行测试

```bash
pytest
```

## 免责声明

本项目仅供学习与技术研究，行情数据来源于公开接口，不构成任何投资建议。
