# ashare-monitor 项目总结（v3：四市场投研 + 低频交易 + 工程化升级）

> 个人投研工作站的完整进化：A 股 / 港股 / 美股 / 数字货币四市场一体化
> 监控、选股、回测与低频自动化交易模拟，并完成三轮同类开源项目借鉴
> 与工程化升级（配置驱动 / 状态机 / 可编程 / 自文档 / Agent 可查询）。
> **113 commits · 348 测试 · 54 CLI 命令 · 22 API 函数 · 23 MCP 工具 · 58 模块**（2026-08-24）

---

## 一、项目定位

从"A 股自选股监控"进化为**跨市场个人投研平台 + 低频自动化交易系统 + Agent 可查询的数据服务**：
- **研究侧**：四市场行情监控、技术信号、财务画像、多视角报告、全市场选股、历史回填
- **交易侧**：策略引擎、模拟交易、组合回测、月度再平衡、风控（止损/熔断）、净值跟踪
- **工程侧**：因子 DSL、Broker 状态机、Python API、自动文档、MCP Server
- **边界**：全部交易功能为模拟（paper trading），实盘通道占位待券商开通（合规）

## 二、四市场能力矩阵

| 能力 | A 股 | 港股 | 美股 | 数字货币 |
|---|---|---|---|---|
| 实时行情 | 新浪/腾讯/东财 | 腾讯 | 新浪/腾讯 | Binance 双域 |
| K 线历史 | 1990 起 | 2002 起 | 1999 起（5748 根）| 2017 起（币安）+ 2010 起（CoinGecko 补）|
| 财务画像 | ✅ 20 维 | ⚠️ 部分 | ✅ ROE/毛利/增速 | ⚠️ 代币经济 + 链上（本机验证）|
| 体检维度 | 20 维 | 11 维 | 5 维 | 4 维 |
| 选股因子 | 6 个 A 股 + DSL 自定义 | — | momentum / lowval | — |
| 多视角报告 | ✅ | ✅ | ✅ | ✅ |

## 三、低频自动化交易平台

```
L0 研究层    四市场行情/选股/体检（信号与候选）
L1 策略层    dividend 股息轮动（选股器 → 目标持仓）
L2 组合层    模拟持仓 / 月度再平衡差额指令
L3 执行层    PaperBroker（现金账户 + 订单状态机）/ executor QMT/PTrade 占位
L4 风控层    单标的上限 20% / ST 黑名单 / 最小市值 / 止损 -15% / 组合熔断 -20%
L5 跟踪层    净值记录（paper_history）/ 周度风控 / 月度换仓
```

**命令**：`strategy dividend/backtest/rebalance/status/orders/risk/track/navreport/breaker/factor`
**回测引擎能力**：涨跌停成交约束 · T+1 说明 · 交易成本模型（bp）· 再平衡频率参数化 ·
IC/IR 因子检验 · 参数网格优化 · 绩效统计 9 项 · HTML 报告（净值/水下/月度热力图）

## 四、工程化升级（同类项目借鉴，2026-08）

| 借鉴项目 | star | 技术模式 | 落地 |
|---|---|---|---|
| qlib（微软）| ~44k | 因子表达式 DSL | `factor_dsl.py`（12 函数 + 运算/比较，O(n)）|
| OpenBB | ~64k | 多入口共享核心 | `api.py`（22 函数，类型与 CLI 同源）|
| OpenBB | ~64k | MCP Server | `mcp_server.py`（零依赖 stdio，23 工具自动注册）|
| backtrader | ~14k | Broker 状态机 | `broker.py`（现金账户 + New→Filled/Rejected/Canceled）|
| akshare | ~20k | 接口文档自动生成 | `docs_gen.py` + `docs/commands.md`（53 命令 8 类）|
| backtesting.py | ~8k | 参数网格优化 | `optimize_backtest`（频率×成本，最优按夏普）|
| pyfolio | ~6k | 绩效深度 + 诊断图 | 统计 9 项 / 月度热力图 / 水下曲线 |
| zvt / QUANTAXIS | ~5-7k | 跨市场统一架构 | AssetProfile + providers（已有，对齐）|

**1k-5k 长尾区间**（adata/easyquotation/efinance/mootdx/tqsdk/pybroker/quantstats）：
数据接口、指标、绩效报告、情绪监控（龙虎榜/两融/人气）已被上述融合覆盖——无重大新差距，如实。

## 五、A 股全栈数据（a-stock-data 融合，`ad` 命令 12 子命令）

`quote` 腾讯富字段（PE/PB/市值，实测校准索引 39/46/44 避坑 43=振幅）· `hot` 同花顺题材 ·
`lhb` 龙虎榜席位 · `unlock` 解禁 · `margin` 两融 · `block` 大宗 · `fundflow` 资金流 120 日 ·
`fin` 新浪三表 · `announce` 巨潮公告 · `reports` 东财研报 + PDF · `eps` 一致预期 · `news` 公告
两融/解禁已接入 check 体检（A 股 20 维）

## 六、数据源与边界（如实）

| 数据源 | 状态 | 备注 |
|---|---|---|
| 腾讯行情/富字段（A 股 + 美股 PE/市值）| ✅ 沙箱可用 | 不封 IP，美股富字段批量实测校准 |
| 东财 datacenter（两融/研报/财报）| ✅ 部分沙箱可用 | 节流防封（em_get 串行+抖动）|
| 东财 push2 行情 | ⚠️ 沙箱 RemoteDisconnected | 本机直连可用 |
| Binance（行情/K 线）| ✅ 双域回退 | 2017 起 + CoinGecko 补 2010 前 |
| CoinGecko / blockchain.info / Lido | ⚠️ 沙箱境外不可达 | 本机直连可用（mock 测试覆盖）|
| akshare 全量 | ⚠️ 部分接口受限 | 多源降级设计 |

## 七、关键验证记录（真实数据）

- 组合回测（2024-01~2026-08）：等权 4 只年化 29.25% vs 沪深 300 的 18.51%，跑赢 10.7pct
- 网格优化：半年再平衡最优（夏普 0.95 / 年化 32.78%）；5bp 成本惩罚仅 -0.18pct
- 涨跌停约束后月度再平衡年化 25.15%→27.50%（涨停被迫保留强势仓）
- IC 检验：动量因子自选股 IC 0.04 → 无效（如实淘汰）；60 日动量 IC 0.0118 零代码检验
- 英伟达：5748 根 K 线，上市以来 +523,607%（年化 45.13%），ROE 101.5% / 毛利率 71.1%
- 茅台体检 20 维：两融融资余额 175.1 亿、研报西南证券"买入"、PE 20.0 / PB 6.49
- 比特币 77,028 USDT 四市场同屏日报；BTC/ETH 各 3293 根（2017 币安起点）
- 模拟运行 2026-08-24 启动（平安 2100 股/比亚迪 200 股/宁德 100 股，81,170 元）
- 性能优化：timing 预计算 O(n²)→O(n)，5748 根 47s→0.06s（780 倍）

## 八、里程碑

| 节点 | 内容 |
|---|---|
| 73 → 83 commits | 选股器六因子 + 历史回补 |
| 83 → 92 | 四市场扩展（美股/币）+ 低频交易平台 |
| 92 → 100 | a-stock-data 七层融合 + check 20 维 |
| 100 → 113 | 万星/5k-10k 借鉴 + 工程化（DSL/Broker/API/文档/MCP）+ 回测报告 + 业务补完 |

## 九、待办与合规

- 待办：实盘通道（QMT/PTrade，券商开通 + 合规报备）· 模拟运行 3 个月验证 ·
  链上数据本机直连验证 · 长尾情绪因子（人气榜/换手率榜单）
- 合规：A 股程序化交易需按 2024《程序化交易管理规定》报备；数字货币境内政策边界；
  当前全部为模拟交易 + 只读数据服务，零实盘风险

## 十、使用入口

- CLI：`python -m ashare_monitor.main <命令>`（详见 docs/commands.md）
- Python：`import ashare_monitor.api as am`（22 函数）
- MCP：`python -m ashare_monitor.main mcp`（23 工具，AI Agent 查询）
- 每日任务：`scripts/run_daily.sh` / `run_weekly.sh` / `setup_schedule_windows.bat`
