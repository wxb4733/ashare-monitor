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

# 历史数据分析（日/周/月线，前复权）
python -m ashare_monitor.main analyze 600519 --days 120 --adjust qfq
python -m ashare_monitor.main analyze 002594 --period weekly --days 60   # 周线看中期趋势
python -m ashare_monitor.main analyze 002594 --period monthly --days 60  # 月线看大级别

# 港股 / 加密货币分析
python -m ashare_monitor.main analyze 00700 --market hk --days 60
python -m ashare_monitor.main analyze BTCUSDT --market crypto --days 60

# 规则化交易信号（结合实时行情；仅供参考，不构成投资建议）
python -m ashare_monitor.main advice 600519 --days 120
python -m ashare_monitor.main advice BTCUSDT --market crypto --days 60

# 技术指标监控（MACD/RSI/KDJ/BOLL，支持日/周/月线）
python -m ashare_monitor.main indicator 600519 --days 120
python -m ashare_monitor.main indicator 002594 --period weekly --days 120  # 周线 MACD 金叉/死叉（中期信号）
python -m ashare_monitor.main indicator BTCUSDT --market crypto --days 60

# 生成复盘报告（默认今天，可指定日期）
python -m ashare_monitor.main review [--date 2026-08-18]

# 回填历史复盘（用本地 klines 库离线生成，需先 backfill --kline）
python -m ashare_monitor.main review --backfill 2002-07-31 [--end 2026-08-19]
# 历史复盘按交易日关联「当时最新已披露财报」（需先 backfill --financial；读 SQLite financials 表）

# 全市场异动扫描（涨幅/跌幅/放量/换手/振幅榜）
python -m ashare_monitor.main scan

# 公告与研报（仅 A 股，带原文链接与机构预测）
python -m ashare_monitor.main news 600519 --days 90

# 上市以来全量数据回填 + 历史统计（行情/公告/研报/财报）
python -m ashare_monitor.main backfill 002594           # 回填全部维度（可增量重跑）
python -m ashare_monitor.main history 002594            # 上市以来统计（区间位置/最高最低）

# 持有期回测：某日买入 X 元，持有 N 个交易日卖出
python -m ashare_monitor.main backtest 002594 --buy-date 2024-01-02 --amount 100000 --hold-days 60,120,250

# 定投回测：近 N 个月每月买入 X 元，持有 M 个交易日后卖出（收益分布统计）
python -m ashare_monitor.main backtest 002594 --dca --months 60 --hold-days 250 --amount 10000 [--detail]

# 多标的定投横向对比（同参数）
python -m ashare_monitor.main backtest 002594 --compare 002594,01211 --hold-days 250 --amount 10000

# 回测可视化：K 线图标注买卖点（HTML）
python -m ashare_monitor.main backtest 002594 --buy-date 2024-01-02 --hold-days 250 --amount 100000 --chart

# 财报分析（A 股人民币 / 港股港元口径，近 6 个报告期）
python -m ashare_monitor.main financial 600519 --periods 6
python -m ashare_monitor.main financial 01211 --market hk --periods 6

# IPO 公司分析（近期新股列表 / 单只详情 / 分析报告）
python -m ashare_monitor.main ipo --limit 30
python -m ashare_monitor.main ipo 马矿股份
python -m ashare_monitor.main ipo --report   # 生成 IPO 分析报告（HTML + Obsidian）
python -m ashare_monitor.main ipo --history 002594,01211   # 历史 IPO 发行分析（A股东财/港股公开资料）

# 导出复盘到 Obsidian（Markdown，需配置 obsidian.vault）
python -m ashare_monitor.main review        # 生成时自动导出
python -m ashare_monitor.main export        # 等效命令

# 周/月复盘汇总报告（基于 SQLite 积累的数据）
python -m ashare_monitor.main report --weekly
python -m ashare_monitor.main report --monthly
python -m ashare_monitor.main report --yearly   # 年报（近 365 天）
```

安装为命令后也可直接使用 `ashare-monitor once` / `ashare-monitor monitor` / `ashare-monitor analyze` / `ashare-monitor advice` / `ashare-monitor indicator` / `ashare-monitor news` / `ashare-monitor financial` / `ashare-monitor ipo` / `ashare-monitor review` / `ashare-monitor export` / `ashare-monitor scan` / `ashare-monitor report`。

## Obsidian 集成（独立知识库）

项目内置一个**独立 Obsidian 知识库** `obsidian-vault/`（可被 Obsidian 直接打开），
复盘报告生成时自动导出 Markdown 进去：

```bash
python -m ashare_monitor.main obsidian init   # 初始化库结构（.obsidian 配置 + 模板 + 首页）
python -m ashare_monitor.main obsidian index  # 重建首页索引（日复盘 + 周/月/年报 wikilink）
python -m ashare_monitor.main review          # 生成复盘并自动导出到 obsidian-vault/A股复盘/
python -m ashare_monitor.main report --weekly|--monthly|--yearly  # 周期报告自动导出到 汇总报告/
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
├── README.md           # 知识库首页（自动维护复盘 + 汇总报告索引）
├── 模板/复盘模板.md     # 复盘笔记模板
├── A股复盘/            # 每日复盘 Markdown（本地数据，git 忽略）
└── 汇总报告/           # 周报 / 月报 / 年报 Markdown（本地数据，git 忽略）
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

## 数据回填与上市以来统计（backfill / history）

```bash
python -m ashare_monitor.main backfill 002594        # 回填全部维度（日K全量/公告/研报/财报）
python -m ashare_monitor.main backfill 002594 --kline # 仅日 K（akshare 优先，腾讯 K 线分段降级）
python -m ashare_monitor.main history 002594          # 上市以来统计
```

- 日 K 入库 `klines` 表（market+code+date 唯一，可增量重跑去重）
- `history` 输出：上市首日/交易天数/上市以来涨幅（年化）/历史最高最低及日期/当前价历史区间位置/距高点回撤/近一年
- 公告/研报/财报分别入库 `announcements` / `research_reports` / `financials` 表

## 持有期回测（backtest）

```bash
python -m ashare_monitor.main backtest 002594 --buy-date 2024-01-02 --amount 100000 --hold-days 60,120,250
```

按"某日买入 X 元 → 持有 N 个交易日 → 卖出"模拟，输出：买入/卖出价与日期、实际成交股数
（按整手：A 股 100 股、港股按每手）、买卖金额、**收益率**、年化、持有期最高/最低价。
支持逗号分隔多档持有期对比；数据优先用已回填的全量 K 线（离线快速）。
注：未计佣金与税费，回测为历史价格模拟，不构成投资建议。

**定投模式（`--dca`）**：每月首个交易日买入固定金额、持有 N 个交易日后卖出（逐笔独立不复利），
统计交易笔数、平均/中位数收益率、胜率、最好/最差一笔、平均年化；`--detail` 看逐笔明细。

**多标的对比（`--compare`）**：同参数跑多个标的的定投统计并列表对比（市场按代码位数自动推断）。

**可视化（`--chart`）**：单笔回测生成 HTML——K 线图（ECharts，涨红跌绿）+ 买卖点标注 +
区间收益大字，成交量高亮持有区间；输出到 `output/backtest-{code}-{date}-{hold}.html`。

## 历史数据分析（analyze）
拉取个股历史 K 线（优先东财 akshare，失败自动降级腾讯 K 线），支持**日 / 周 / 月线**多周期
（`--period daily|weekly|monthly`，年化波动率按周期数自动换算：日线 250/365、周线 52、月线 12），输出：

- **概览**：最新收盘、区间涨跌幅、上涨/下跌天数与胜率
- **波动指标**：年化波动率、近 20 周期波动率、最大回撤、平均振幅
- **趋势**：MA5/10/20/60 与收盘价相对位置
- **量能**：近 5 / 20 周期均量与量比

`indicator` 同样支持 `--period`（周线 MACD 金叉/死叉是中期趋势信号，月线看大级别）。

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

# 择时买入提醒（收盘后扫描自选股技术性买点信号）
python -m ashare_monitor.main timing               # 扫描全部自选股
python -m ashare_monitor.main timing 002594 --report
python -m ashare_monitor.main timing --push        # 有信号推送 webhook（需 ASHARE_MONITOR_WEBHOOK）
# 信号规则：强势回踩MA20 / 深度回调止跌 / MACD金叉 / RSI超卖回升 / 放量突破
# 每个信号标注历史命中率（该规则在标的上近 5 年信号触发后 5 日收益为正比例）
# 信号同时自动出现在当日复盘报告的「择时买入信号」板块

# 持仓管理与盈亏日报（positions 配置在 config.local.yaml）
python -m ashare_monitor.main position            # 收盘价盈亏
python -m ashare_monitor.main position --live --report
python -m ashare_monitor.main position --push     # 推送盈亏日报 webhook

# 事件日历提醒（解禁/分红除权/业绩预告，未来 N 天）
python -m ashare_monitor.main events --days 30 --report --push

# 资金面监控（个股主力资金流 + 沪深港通概要）
python -m ashare_monitor.main fundflow --report --push
# 注意：北向净买入额度自 2024-08 起停止披露；个股资金流 push2 接口偶发不稳（本机运行较稳定）

# 股东分析（十大股东 + 股东户数趋势）
python -m ashare_monitor.main holders 002594 --report --push
# 解读：户数半年减少>10% → 筹码集中（潜在看涨信号）；增加>10% → 分散（潜在承压）
# 数据源：东方财富 F10（十大股东）/ RPT_HOLDERNUM_DET（户数历史）

# 个股全方位体检（行情/技术/基本面/筹码/资金/事件/择时 一键评分）
python -m ashare_monitor.main doctor 002594 --report

# 组合定投回测（多标的按权重，月度对齐合成组合收益）
python -m ashare_monitor.main portfolio 002594,01211 --weights 60,40 --amount 100000 --report
# 注意：港股 1 手 500 股，月投金额需买得起整手（如比亚迪H约3.7万港元/手）
# 盘中预警实时推送：monitor 已支持 webhook（设置 ASHARE_MONITOR_WEBHOOK 环境变量即可）

# arXiv 论文监测（以指定股票代码对应公司为主题/署名单位）
python -m ashare_monitor.main arxiv 002594 --report     # 比亚迪（内置 BYD 映射，默认覆盖近 40 年）
python -m ashare_monitor.main arxiv 000000 --name Huawei --report  # 自定义英文名
# 检索策略：arXiv API abs: 摘要含公司名（API 不返回 affiliation 字段，内容匹配）；--days 可调范围
# 内置映射：002594/01211→BYD 300750→CATL 600519→Moutai 等；config.local.yaml 的 arxiv 段可覆盖
# 用途：跟踪上市公司 AI/技术研发动态（华为诺亚方舟：SysEvolve/MoE/Aicir 等）

# HuggingFace 监测（模型 + 收录论文）
python -m ashare_monitor.main hf 00700 --report     # 腾讯（tencent 组织）
python -m ashare_monitor.main hf 09988 --report     # 阿里（Qwen 组织）
python -m ashare_monitor.main hf 002594 --org BYD-Auto  # 自定义组织
# 数据源：HF API（默认 hf-mirror.com 国内镜像，可设 HF_ENDPOINT 覆盖）
# 内置组织映射：00700→tencent 09988→Qwen 03690→bytedance-research 等；config 的 hf 段可覆盖

# 诉讼监控（自选股重大诉讼披露）
python -m ashare_monitor.main litigation --report --push
# 数据源：巨潮资讯 p_sysapi1055（经 akshare）；入库 SQLite 去重（code+period）
# 注意：仅覆盖达到重大诉讼披露标准的公司；未出现=近 N 天无重大诉讼（正常）
# 专利数据：免费源不可用（Google Patents 被墙/CNIPA 需登录），需天眼查/智慧芽连接器

# 公司档案（工商信息 + 股权结构）
python -m ashare_monitor.main profile 002594 --report
# 工商来源：巨潮资讯 stock_profile_cninfo（法人/注册资本/成立上市日期/地址/主营/经营范围）
# 股权来源：东财 F10 十大股东（复用 holders）；实控人为规则化推断（持股最多自然人）
# 完整股权穿透需企查查/天眼查连接器

# 政府侧企业动态（中标/拿地/补助/税收优惠公告）
python -m ashare_monitor.main gov --report --push
# 数据源：东财公告标题关键词过滤（招投标/拿地/补助补贴/资质税收四类）
# 注意：为公告侧动态（公司主动披露）；完整政府数据（纳税信用/社保人数/招投标记录/拿地档案）
# 免费源全反爬（政府采购网403/土地市场网418），需天眼查/上奇/帆软连接器

# 官方网站链接档案 + 官网公告监控
python -m ashare_monitor.main site --report
# 官网链接：工商档案自动获取（巨潮）+ config.local.yaml 的 sites 段扩展
#   sites: {002594: {website: ..., notice_url: ..., ir_url: ..., social: ...}}
# 公告监控：可配置 notice_url 抓取（多数官网公告页为 JS 动态加载，抓不到时如实提示，
# 权威官方公告以东财公告为准）

# 公司信号监控（8 个新命令）
python -m ashare_monitor.main insider 002594 --report   # 增减持+回购（公告信号）
python -m ashare_monitor.main pledge --report           # 股权质押（巨潮）
python -m ashare_monitor.main rating 002594 --report    # 券商研报（含EPS预测）
python -m ashare_monitor.main lhb 002594                # 龙虎榜（自选股上榜）
python -m ashare_monitor.main north 002594              # 北向持股（2024-08-16后停每日披露，历史保留）
python -m ashare_monitor.main block 002594              # 大宗交易（折溢率）
python -m ashare_monitor.main valuation 002594 --report # 估值分位（PE/PB 历史百分位）
python -m ashare_monitor.main sector 002594 --report    # 月度产销快报（行业景气先行指标）
# 说明：产销快报销量在公告正文（东财内容 API 提取，沙箱偶发空体需本机验证）

# 信号聚合雷达 + 一键日报（汇总裁决层）
python -m ashare_monitor.main radar --report --push   # 18 维信号多空计分（≥+2偏多/≤-2偏空）
python -m ashare_monitor.main daily --report --push   # 一键日报（行情+雷达+择时+事件+估值+研报+增减持+K线健康）
# radar 计分：技术/筹码/资金/估值/事件/增减持/质押/研报/产销；缺失维度不计分

# 汽车行业景气数据（乘联会 CPCA）
python -m ashare_monitor.main industry --report --push
# 月度总销量/新能源渗透率/厂商排名TOP10；口径：批发量
# 说明：中汽研(catarc.info)官方数据产品需授权；本命令用乘联会公开数据
