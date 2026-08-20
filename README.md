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

# 公告与研报（仅 A 股，带原文链接与机构预测）
python -m ashare_monitor.main news 600519 --days 90

# 财报分析（仅 A 股，近 6 个报告期）
python -m ashare_monitor.main financial 600519 --periods 6

# IPO 公司分析（近期新股列表 / 单只详情）
python -m ashare_monitor.main ipo --limit 30
python -m ashare_monitor.main ipo 马矿股份

# 导出复盘到 Obsidian（Markdown，需配置 obsidian.vault）
python -m ashare_monitor.main review        # 生成时自动导出
python -m ashare_monitor.main export        # 等效命令

# 周/月复盘汇总报告（基于 SQLite 积累的数据）
python -m ashare_monitor.main report --weekly
python -m ashare_monitor.main report --monthly
```

安装为命令后也可直接使用 `ashare-monitor once` / `ashare-monitor monitor` / `ashare-monitor analyze` / `ashare-monitor advice` / `ashare-monitor indicator` / `ashare-monitor news` / `ashare-monitor financial` / `ashare-monitor ipo` / `ashare-monitor review` / `ashare-monitor export` / `ashare-monitor scan` / `ashare-monitor report`。

## Obsidian 集成（独立知识库）

项目内置一个**独立 Obsidian 知识库** `obsidian-vault/`（可被 Obsidian 直接打开），
复盘报告生成时自动导出 Markdown 进去：

```bash
python -m ashare_monitor.main obsidian init   # 初始化库结构（.obsidian 配置 + 模板 + 首页）
python -m ashare_monitor.main obsidian index  # 重建首页复盘索引（wikilink）
python -m ashare_monitor.main review          # 生成复盘并自动导出到 obsidian-vault/A股复盘/
```

```yaml
obsidian:
  vault: "obsidian-vault"   # 独立库目录（相对 config 解析；留空禁用）
  reports_dir: "A股复盘"     # 库内复盘子目录
```

库结构：

```
obsidian-vault/
├── .obsidian/          # 应用配置（新文件默认入复盘目录、启用模板）
├── README.md           # 知识库首页（自动维护复盘索引）
├── 模板/复盘模板.md     # 复盘笔记模板
└── A股复盘/            # 每日复盘 Markdown（本地数据，git 忽略）
```

导出的 Markdown 包含 frontmatter（date/tags，可检索与双链）、
大盘指数 / 技术指标 / 当日表现 / 预警时间线 / 财报速览 / 公告与研报（含原文链接）/
近期 IPO 各板块表格；K 线图（ECharts）无法入 Markdown，以链接指向 HTML 报告。
复盘数据由 vault 内 `.gitignore` 排除，仅模板与配置入库。

## IPO 公司分析（ipo）

`ipo` 命令分析新股（东财新股申购/上市报表 `RPTA_APP_IPOAPPLY` 直连）：

- **`ipo`（无参数）**：近期新股列表（代码/名称/交易所/申购日/发行价/行业 PE/募资/阶段状态），含北交所（920 开头）
- **`ipo <代码或名称>`**：单只新股详情 + 规则化分析
  - 发行阶段判定（待定价/待申购/待上市/已上市）
  - 发行 PE vs 行业 PE 对比（估值偏贵/便宜/持平，PE 字段缺失时自动跳过）
  - 募资完成度（超募/缩募提示）
  - 已上市新股：现价 vs 发行价（**破发提示**）

```bash
python -m ashare_monitor.main ipo --limit 30   # 近期新股
python -m ashare_monitor.main ipo 马矿股份      # 单只分析
```

已知限制：东财该报表多数新股的发行市盈率字段为空，PE 对比仅在字段可用时输出。
输出附完整免责声明（IPO 分析为投资参考信息，不构成投资建议）。

## 财报分析（financial）

`financial` 命令查看被监控标的的财务业绩（**仅 A 股**，东财业绩报表接口 → akshare 兜底）：

- **多期趋势表**：最近 N 个报告期的营收/净利（亿元）及同比、ROE、毛利率（涨红跌绿）
- **财报速览**：增速环比变化（改善/放缓）、近 3 期增长连续性、ROE/毛利率/净利率水平、每股经营现金流是否覆盖净利润（盈利质量）

```bash
python -m ashare_monitor.main financial 600519 --periods 6
```

输出附完整免责声明（财报分析为投资参考信息，不构成投资建议）。

## 公告与研报（news）

`news` 命令查看被监控标的的公开信息（**仅 A 股**，港股/加密货币暂无数据源）：

- **公告**：东财公告接口（最近 N 条，含原文链接）
- **研报**：东财研报接口（机构名称、报告标题、**预测 EPS / 预测 PE**、原文链接）
- **持久化**：拉取结果自动存入 SQLite（`data/ashare_monitor.db` 的 `announcements` / `research_reports` 表，url 唯一去重），随用随查、离线可读

```bash
python -m ashare_monitor.main news 600519 --days 90   # 拉取 + 入库
python -m ashare_monitor.main news 600519 --local     # 仅读数据库，不联网
python -m ashare_monitor.main news --watchlist --days 30  # 批量采集全部 A 股自选股入库
```

数据源自动降级：东财直连接口 → akshare。收盘复盘报告自动附「公告与研报」板块，
每只自选股展示最近公告与研报标题及原文链接（拉取时同步入库）——复盘时快速定位"异动是否有消息面支撑"。

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
- **财报速览**：每只 A 股自选股最新报告期的营收/净利及同比、ROE、毛利率
- **公告与研报**：最近公告与研报（含原文链接）
- **近期 IPO**：待申购/待上市新股列表（发行价、行业 PE、募资）
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
