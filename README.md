# ashare-monitor

[![CI](https://github.com/wxb4733/ashare-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/wxb4733/ashare-monitor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-357-green.svg)](https://github.com/wxb4733/ashare-monitor/actions)
[![MCP Tools](https://img.shields.io/badge/MCP%20tools-23-orange.svg)](src/ashare_monitor/mcp_server.py)

**个人跨市场投研平台 + 低频自动化交易模拟** —— 一个命令，覆盖 A 股 / 港股 / 美股 / 数字货币的
行情监控、选股体检、企业画像、策略回测与模拟盘，还可被 AI Agent 直接查询。

```
四市场行情 → 五类预警 → 落盘 → 收盘复盘 HTML → Obsidian 知识库
    ↕ 六因子选股 / 22 维体检 / 专利画像 / 回测 / 模拟盘
```

---

## 📋 功能全景（你能用它做什么）

| 板块 | 能力 | 入口 |
|---|---|---|
| **📈 行情监控** | 四市场实时行情（多源降级）、涨跌幅/盘口/振幅/大单预警、全市场异动扫描 | `monitor` / `once` / `scan` |
| **🔍 选股体检** | 六因子选股（股息率/SGR/利润率/市占/低估值/成长）+ DSL 自定义因子；个股 22 维体检（A 股） | `screen` / `check` / `doctor` / `radar` |
| **🧠 研究分析** | 技术指标（MACD/RSI/KDJ/BOLL）、交易信号、持有期/定投回测、信号命中率验证、财报/研报/公告/IPO | `analyze` / `advice` / `indicator` / `backtest` / `verify` |
| **🏢 企业画像** | 工商画像（天眼查）、专利/论文布局（智慧芽）、两融/解禁/龙虎榜/大宗/北向/增减持 | `check` / `ad` / `profile` |
| **🤖 低频交易** | 策略引擎 → 目标持仓 → 模拟撮合 → 再平衡 → 风控（止损/熔断）→ 净值跟踪 | `strategy` |
| **📊 报告复盘** | 收盘复盘 HTML（含知识产权区块）、日报/周报/月报、Obsidian 知识库导出、专利横向对比报告 | `review` / `daily` / `period` / `report` / `export` |
| **🔌 开放接口** | Python API（22 函数）、MCP Server（23 工具，AI Agent 查询）、企业数据导入（Wind/天眼查/智慧芽） | `mcp` / `import_data.py` |

> 规模：**54 个 CLI 命令 · 22 个 Python API · 23 个 MCP 工具 · 357 项测试 · 129+ commits**

---

## 🚀 快速开始（5 分钟）

```bash
# 1. 安装（Python ≥ 3.10）
cd ashare-monitor
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"        # Windows；macOS/Linux 用 .venv/bin/pip

# 2. 配置自选股与预警（编辑 config.yaml 的 watchlist / alerts）
#    A 股 6 位代码 / 港股 5 位 + market: hk / 币安交易对 + market: crypto / 美股代码

# 3. 第一次跑起来
.venv/Scripts/python -m ashare_monitor.main once        # 单次行情快照（全部自选股）
.venv/Scripts/python -m ashare_monitor.main monitor     # 持续监控（交易时段自动预警）

# 4. 收盘复盘（生成 output/review-YYYY-MM-DD.html）
.venv/Scripts/python -m ashare_monitor.main review
```

**一条命令看一只股票的全貌**（以比亚迪为例）：

```bash
python -m ashare_monitor.main analyze 002594        # 历史数据分析
python -m ashare_monitor.main advice 002594         # 规则化交易信号
python -m ashare_monitor.main indicator 002594      # MACD/RSI/KDJ/BOLL
python -m ashare_monitor.main check 002594          # 22 维体检（含工商画像/专利/两融/解禁）
python -m ashare_monitor.main backtest 002594       # 持有期回测
python -m ashare_monitor.main history 002594        # 上市以来统计（需先 backfill）
```

---

## 🏗 技术报告（用户视角）

### 系统架构：从数据到决策的分层设计

```
L0 研究层   四市场行情 / 选股 / 体检（信号与候选）
L1 策略层   dividend 股息轮动等（选股器 → 目标持仓）
L2 组合层   模拟持仓 / 月度再平衡差额指令
L3 执行层   PaperBroker（现金账户 + 订单状态机）/ executor QMT/PTrade 占位
L4 风控层   单标的上限 20% / ST 黑名单 / 最小市值 / 止损 -15% / 组合熔断 -20%
L5 跟踪层   净值记录 / 周度风控 / 月度换仓
```

数据流：`多源行情 → 五类预警 → SQLite 落盘 → 收盘 HTML 复盘 → Obsidian 知识库`。
所有交易功能均为**模拟盘**（paper trading），实盘通道留 QMT/PTrade 占位。

### 四市场能力矩阵

| 能力 | A 股 | 港股 | 美股 | 数字货币 |
|---|---|---|---|---|
| 实时行情 | 新浪/腾讯/东财 | 腾讯 | 新浪/腾讯 | Binance 双域 |
| K 线历史 | 1990 起 | 2002 起 | 1999 起（5748 根）| 2017 起（币安）+ 2010 起（CoinGecko）|
| 体检维度 | **22 维** | 11 维 | 5 维 | 4 维 |
| 选股因子 | 6 个 + DSL 自定义 | — | momentum / lowval | — |
| 企业画像/专利 | ✅ 40 家回填 | ✅ 小米 | ✅ 英伟达 | — |

### 数据源与边界（如实标注）

| 数据源 | 用途 | 状态 |
|---|---|---|
| 新浪/腾讯/东财 | 行情快照、K 线 | ✅ 多源自动降级 |
| 东方财富 datacenter | 两融/研报/财报/解禁/龙虎榜 | ✅ 节流防封 |
| **Wind** | K 线校准（权威前复权）| ✅ MCP 会话内回填 |
| **天眼查** | 工商画像 | ✅ MCP 会话内回填 |
| **智慧芽** | 专利/论文（含法律状态/IPC）| ✅ MCP 会话内回填（采样快照）|
| Binance / CoinGecko | 币行情/K 线/链上 | ✅ 双域回退（境外源沙箱受限时需本机）|
| akshare | 全市场数据兜底 | ⚠️ 部分接口受限 |

> 诚实说明：专利数据为每标的最新 8~15 件采样快照（非全量，高股息队列为 8~12 件）；
> 境外 API（CoinGecko 等）在受限网络下不可达，程序自动降级并以 mock 测试覆盖。

### 关键验证记录（真实数据）

- 组合回测（2024-01 ~ 2026-08）：等权 4 只**年化 29.25%** vs 沪深 300 的 18.51%，跑赢 10.7pct
- 网格优化：半年再平衡最优（夏普 0.95 / 年化 32.78%）
- IC 检验：60 日动量因子 IC 0.0118（如实标注有效性）；动量因子自选股 IC 0.04 已淘汰
- 英伟达：5748 根 K 线，上市以来 +523,607%（年化 45.13%）
- 性能优化：timing 预计算 O(n²)→O(n)，5748 根 47s→0.06s（**780 倍**）
- Wind 校准：7 日 K 线与 akshare 逐点一致

### 合规与边界

- 全部交易为**模拟**，零实盘风险；A 股程序化交易按 2024《程序化交易管理规定》需报备后才可实盘（见 `docs/compliance_checklist.md`）
- 数字货币模块仅做行情监控与链上研究，不涉及交易
- 输出为数据分析，不构成投资建议

---

## 📖 使用手册

### 5.1 配置文件

`config.yaml`（示例默认）——复制为 `config.local.yaml` 自定义，避免污染仓库：

```yaml
watchlist:                 # 自选股（4 市场混排）
  - { code: "600519", name: "贵州茅台" }
  - { code: "01211", name: "比亚迪股份", market: hk }
  - { code: "NVDA",   name: "英伟达",   market: us }
  - { code: "BTCUSDT", name: "比特币",   market: crypto }
alerts:                    # 预警规则
  change_pct_threshold: 3.0     # 涨跌幅 ≥3% 预警
  weibi_threshold: 80           # 盘口委比失衡预警
  big_order_threshold: 5000     # 单档大单（手）预警
  amplitude_threshold: 5.0      # 振幅预警
monitor:
  interval_seconds: 30          # 轮询间隔
  auto_review: true             # 收盘自动复盘
quotes:
  sources: ["sina", "tencent", "eastmoney"]   # 多源降级
review:
  indexes: ["sh000001", "sz399001", "sz399006"]  # 大盘对照
obsidian:
  vault: "obsidian-vault"       # Obsidian 知识库（可留空禁用）
```

### 5.2 每日工作流

```bash
# 盘中：持续监控（自动预警 + 收盘自动复盘）
python -m ashare_monitor.main monitor

# 收盘后：一键日报 → 复盘 → 导出 Obsidian
python -m ashare_monitor.main daily
python -m ashare_monitor.main review
python -m ashare_monitor.main export            # Obsidian Markdown
python -m ashare_monitor.main report --weekly   # 周度汇总
```

定时任务（Windows）：右键管理员运行 `scripts/setup_schedule_windows.bat`，
注册「工作日 15:40 日报」与「周日 20:00 周报」两个计划任务。

### 5.3 选股与体检

```bash
# 六因子选股（A 股）：股息率 / 可持续增长率 / 高利润率 / 市占率 / 低估值 / 高成长
python -m ashare_monitor.main screen --metric dividend --top 20
python -m ashare_monitor.main screen --metric sgr     # SGR 可持续增长率
python -m ashare_monitor.main screen --metric lowval   # 低估值（PE/PB 分位）
python -m ashare_monitor.main screen --market us --metric momentum   # 美股动量

# DSL 自定义因子：如 (close/Ref(close,20)-1)*100 动量
python -m ashare_monitor.main strategy factor --expr "(close/Ref(close,20)-1)*100"

# 个股体检：check（22 维） / doctor（评分） / radar（多空计分）
python -m ashare_monitor.main check 002594
python -m ashare_monitor.main doctor 002594
python -m ashare_monitor.main radar
```

A 股 22 维体检内容：行情、K 线历史、择时、基本面、估值分位、行业、研报数、事件、
基金持仓、筹码、增减持、龙虎榜、股权质押、**工商画像（天眼查）**、**知识产权（智慧芽专利/论文）**、
**两融**、**解禁**等。

### 5.4 研究分析

```bash
# 技术指标与信号
python -m ashare_monitor.main indicator 002594          # MACD/RSI/KDJ/BOLL
python -m ashare_monitor.main advice 002594             # 规则化信号
python -m ashare_monitor.main timing                    # 收盘后择时买点扫描
python -m ashare_monitor.main verify 002594             # 信号历史命中率

# 回测
python -m ashare_monitor.main backtest 002594 --amount 100000 --hold-days 60,120,250
python -m ashare_monitor.main backtest 002594 --dca --months 60 --detail   # 定投
python -m ashare_monitor.main backtest --compare 002594,01211 --dca        # 多标的对比
python -m ashare_monitor.main portfolio --codes 600519,000001,300750,002594  # 组合定投

# 基本面与资讯
python -m ashare_monitor.main financial 600519          # 财报（近 6 报告期）
python -m ashare_monitor.main news 600519               # 公告与研报
python -m ashare_monitor.main ipo                       # IPO 列表/详情/报告
python -m ashare_monitor.main events                    # 解禁/除权/业绩日历
```

### 5.5 低频自动化交易（模拟盘）

```bash
python -m ashare_monitor.main strategy dividend        # 股息轮动 → 目标持仓
python -m ashare_monitor.main strategy backtest        # 策略回测（涨跌停/成本约束）
python -m ashare_monitor.main strategy rebalance       # 月度再平衡差额指令
python -m ashare_monitor.main strategy orders          # 订单历史（状态机）
python -m ashare_monitor.main strategy risk            # 止损检查（-15%）
python -m ashare_monitor.main strategy breaker         # 组合熔断（-20%）
python -m ashare_monitor.main strategy track           # 净值记录
python -m ashare_monitor.main strategy navreport       # 净值报告 HTML
```

回测引擎能力：涨跌停成交约束 · T+1 · 交易成本（bp）· 再平衡频率参数化 · IC/IR 因子检验 ·
参数网格优化 · 绩效统计 9 项 · HTML 报告（净值/水下/月度热力图）。

### 5.6 数据回填与企业数据导入

```bash
# 历史数据回填（建议先 backfill 再分析）
python -m ashare_monitor.main backfill --kline --all        # 全量 K 线（A 股 1990 起）
python -m ashare_monitor.main backfill --financial          # 财报
python -m ashare_monitor.main backfill_dividend             # 历史股息率（1990 起）
python -m ashare_monitor.main backfill_sgr                  # SGR 历史（1995 起）
```

**企业级数据（Wind / 天眼查 / 智慧芽）**——MCP 连接器会话内拉取 → `import_data.py` 落库 → check/复盘消费：

```python
from ashare_monitor.import_data import (
    import_klines_json,        # Wind K 线 → klines 表（幂等）
    import_company_profile,    # 天眼查画像 → company_profiles 表
    import_ip_assets,          # 智慧芽专利/论文 → ip_assets 表
)
```

回填脚本样例：`scripts/backfill_profiles.py` / `backfill_ip.py` / `backfill_wind_kline.py` /
`backfill_screener_pipeline.py`（高股息选股 → 待回填队列）/ `gen_queue_westock.py`
（东财不可达时用腾讯自选股富字段构造真实队列）。
专利横向对比报告自动生成：`python scripts/patent_report.py` → `docs/patent_landscape.md`。
> 已回填规模（2026-08-26）：**40 家工商画像 · 40 家知识产权（410 件专利采样 + 79 篇论文）**，
> 覆盖核心 6 家 + 高股息队列 34 家。

### 5.7 Python API（22 函数）

```python
import ashare_monitor.api as am

am.quote("002594")                  # 实时行情
am.quotes(["600519", "00700"])      # 多标的行情
am.kline("002594")                  # 本地 K 线
am.history("002594")                # 上市以来统计
am.profile("NVDA")                  # 五维资产画像
am.check("002594")                  # 22 维体检
am.screen(market="ashare", metric="dividend")   # 选股
am.backtest(...)                    # 组合回测
am.paper_trade("002594", 100, 10000)   # 模拟买入
am.paper_positions()                # 模拟持仓
am.factor_ic("momentum")            # 因子 IC 检验
```

### 5.8 MCP / AI Agent 查询（23 工具）

```bash
python -m ashare_monitor.main mcp     # 启动 MCP Server（stdio）
```

工具清单：`quote / quotes / kline / history / profile / check / screen / backtest /
backtest_rebalanced / factor_expr / factor_ic / factor_list / paper_*（trade/positions/
report/orders）/ detect_market / ad_*（quote/hot/lockup/margin/reports/financial）`。
任何 MCP 客户端（Claude Code / WorkBuddy 等）接入后，AI 可直接问"比亚迪体检怎么样"
"高股息 Top10 有哪些"。

### 5.9 A 股全栈数据（ad 命令）

```bash
python -m ashare_monitor.main ad quote 002594      # 腾讯富字段（PE/PB/市值）
python -m ashare_monitor.main ad hot               # 同花顺当日强势股
python -m ashare_monitor.main ad lhb 002594        # 龙虎榜席位
python -m ashare_monitor.main ad unlock 002594     # 解禁日历
python -m ashare_monitor.main ad margin 002594     # 两融明细
python -m ashare_monitor.main ad fundflow 002594   # 资金流 120 日
python -m ashare_monitor.main ad fin 002594        # 新浪三表
python -m ashare_monitor.main ad announce 002594   # 巨潮公告
python -m ashare_monitor.main ad reports 002594    # 东财研报 + PDF
python -m ashare_monitor.main ad eps 002594        # 一致预期
```

---

## 📚 命令速查（54 命令，按板块）

| 板块 | 命令 |
|---|---|
| **监控** | `monitor` `once` `scan` `radar` `fundflow` `holders` `litigation` `insider` `pledge` `rating` `lhb` `north` `block` `events` |
| **体检分析** | `check` `doctor` `analyze` `advice` `indicator` `verify` `timing` `profile` `valuation` |
| **选股** | `screen`（六因子）`dividend_rank` |
| **回测交易** | `backtest` `portfolio` `position` `strategy`（10 子命令）`buyer` `insider_view` |
| **数据回填** | `backfill` `backfill_kline` `backfill_indicators` `backfill_sgr` `backfill_dividend` `history` |
| **报告导出** | `review` `daily` `report` `period` `export` `obsidian` |
| **数据资讯** | `news` `financial` `ipo` `ad`（12 子命令）`arxiv` `hf` |
| **行业** | `sector` `industry` `gov` `site` |
| **开放接口** | `mcp` |

> 完整参数见 `docs/commands.md`（自动生成，与 `--help` 一致）。

---

## 📁 项目结构

```
src/ashare_monitor/
├── main.py            # CLI 入口（54 命令）
├── api.py             # Python API（22 函数，与 CLI 同源）
├── mcp_server.py      # MCP Server（23 工具，零依赖 stdio）
├── import_data.py     # 企业数据导入（Wind/天眼查/智慧芽落库）
├── check.py           # 个股体检（A 股 22 维）
├── screen.py          # 六因子选股器
├── strategy.py        # 低频策略引擎（dividend 轮动等）
├── broker.py          # PaperBroker 订单状态机
├── factor_dsl.py      # 因子表达式 DSL
├── review.py          # 收盘复盘 HTML
├── obsidian_vault.py  # Obsidian 知识库
├── providers/         # 多市场数据源（四市场统一抽象）
├── profile.py         # 五维资产画像（市值/供给/增长/收益/估值）
└── a_stock_data.py    # A 股全栈数据（ad 命令）
scripts/               # 定时任务 / 回填 / 报告生成
docs/                  # commands.md / patent_landscape.md / compliance_checklist.md
tests/                 # 357 项测试
```

---

## 🧪 测试与开发

```bash
python -m pytest tests/ -q                # 357 项全量测试
python scripts/check_health.py            # CI 健康检查（MCP 工具数 + 3.10 语法扫描）
```

CI（GitHub Actions）：Python 3.10/3.11/3.12 矩阵 + 覆盖率 + 健康检查。
贡献新维度时，请同步暴露为 API 函数与 MCP 工具（健康检查会拦截遗漏）。

---

## ❓ FAQ

**Q：数字货币需要翻墙吗？** 币安行情走双域回退，CoinGecko 等境外源在受限网络不可达时会
自动降级；链上数据需本机直连验证（沙箱受限，如实标注）。

**Q：专利/工商画像数据哪来的？** 天眼查（工商）+ 智慧芽（专利/论文）通过 MCP 连接器在
会话内拉取，由 `import_data.py` 落库；每标的专利为最新 15 件采样快照，非全量。

**Q：可以实盘交易吗？** 当前仅模拟盘。实盘需券商开通 QMT/PTrade + 按 2024《程序化交易
管理规定》报备，流程见 `docs/compliance_checklist.md`。

**Q：数据会过期吗？** 行情实时；画像/专利在 check 中标注"X 天前更新"，>90 天提示回补。

---

## ⚠️ 免责声明

本项目为个人研究与自动化模拟工具，输出基于公开数据与量化分析，**仅供参考，不构成投资建议**。
市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力独立判断，必要时咨询持牌专业机构。
过往表现不预示未来收益。全部交易功能为模拟，不涉及真实资金。
