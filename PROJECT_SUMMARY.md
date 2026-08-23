# ashare-monitor 项目总结（2026-08 四市场扩展版）

> 个人投研工作站：A 股 / 港股 / 美股 / 数字货币四市场一体化监控与选股。
> 84 commits · 273 测试 · 59 命令

## 一、项目定位

从"A 股自选股监控"发展为**跨市场个人投研平台**——统一架构承载四个市场：
行情监控、技术信号、财务画像、多视角报告、全市场选股、历史回填。

## 二、四市场能力矩阵

| 能力 | A 股 | 港股 | 美股 | 数字货币 |
|---|---|---|---|---|
| 实时行情 | 新浪/腾讯/东财 | 腾讯 | 新浪/腾讯 | Binance |
| K 线历史 | 1990 起（东财/腾讯/新浪）| 2002 起 | 1999 起（东财）| 2017 起（币安）+ 2010 起（CoinGecko 补）|
| 财务画像 | ✅ 18 维 | ⚠️ 部分 | ✅ ROE/毛利/增速 | ⚠️ 代币经济（CoinGecko，本机验证）|
| 体检维度 | 18 维 | 11 维 | 5 维 | 4 维 |
| 选股因子 | 6 个（股息/SGR/利润率/市占率/低估/成长）| — | ⚠️ 待数据源 | — |
| 历史回填 | 股息率/SGR/增速/估值 1995 起 | K 线 | K 线 | K 线 + CoinGecko 补段 |
| 多视角报告 | ✅ | ✅ | ✅ | ✅ |

## 三、架构（五层通用化）

```
L5 应用层      monitor / radar / period(日/周/月) / check / history / screen
L4 因子引擎    factor 注册表：dividend / sgr / margin / share / lowval / growth
L3 画像层      AssetProfile 五维接口（市值/供给/增长/收益/估值）
               └ 实现：stock_profile / hk / us_profile / crypto_profile
L2 数据模型    Quote / Kline(OHLCV) 领域无关；SQLite 按 market 分桶
L1 数据源      eastmoney / tencent / sina / tencent_hk / sina_us / tencent_us / binance
```

**通用化关键**：领域差异被隔离在 L1（数据源适配）与 L3（画像实现），
L2/L4/L5 跨市场零改动。`build_profile` 一个入口分发四个市场。

## 四、主要命令

```bash
# 监控
python -m ashare_monitor.main monitor                 # 盘中异动监控
python -m ashare_monitor.main radar 002594            # 信号雷达
python -m ashare_monitor.main period --period daily   # 多视角日报（四市场）
# 体检
python -m ashare_monitor.main check 002594            # A 股 18 维
python -m ashare_monitor.main check 01810             # 港股 11 维
python -m ashare_monitor.main check NVDA              # 美股 5 维
python -m ashare_monitor.main check BTCUSDT --market crypto  # 币 4 维
# 选股（A 股全市场 6 因子）
python -m ashare_monitor.main screen --metric dividend   # 高股息率
python -m ashare_monitor.main screen --metric sgr        # 持续增长率
python -m ashare_monitor.main screen --metric margin     # 高利润率
python -m ashare_monitor.main screen --metric share      # 市场占有率
python -m ashare_monitor.main screen --metric lowval     # 低估
python -m ashare_monitor.main screen --metric growth     # 高成长
# 历史回填
python -m ashare_monitor.main backfill 002594            # K 线
python -m ashare_monitor.main backfill_dividend          # 历史股息率（1995 起）
python -m ashare_monitor.main backfill_sgr               # SGR 历史
python -m ashare_monitor.main backfill_indicators        # 增速/估值历史
python -m ashare_monitor.main backfill NVDA --market us  # 美股 K 线
python -m ashare_monitor.main backfill BTCUSDT --market crypto  # 币 K 线（自动 CoinGecko 补段）
python -m ashare_monitor.main dividend_rank --sort cum-yield  # 股息率榜单时长
```

## 五、数据源与边界（如实）

| 数据 | 源 | 沙箱状态 | 边界说明 |
|---|---|---|---|
| A 股行情/K 线 | 东财/腾讯/新浪 | 东财域不稳 | 多源降级已实现 |
| 港股行情 | 腾讯 | ✅ | 财务/估值接口受限 |
| 美股行情 | 新浪/腾讯 | ✅ | 财务用东财美股指标 |
| 美股 K 线 | 东财 stock_us_daily | ✅（5748 根验证）| 前复权口径 |
| 币行情/K 线 | Binance 双域 | ✅（vision 域）| api.binance.com 沙箱超时，自动降级 |
| 币历史 | CoinGecko | ❌ 沙箱不可达 | 本机直连补全（收盘价近似 OHLC）|
| 美股全市场估值 | 无免费源 | — | **缺口：美股选股器待数据源** |
| 币质押收益/通胀率 | 链上数据 | — | 缺口：需链上 RPC |

## 六、关键验证记录（真实数据）

- 比亚迪体检：ROE 1.6% 净利 -55.4%（2026Q1）/ PE 29.9(PB 3% 分位)
- 小米（按比亚迪标准）：K 线 2002 根 / ROE 18.3% / PE≈17.9 / MACD 金叉
- 英伟达：5748 根（1999 起）上市以来 +523,607% 年化 45.1% / ROE 101.5% 毛利率 71.1%
- 比特币：3293 根（币安）+ CoinGecko 补 2010 起 / 最新 7.7 万美元
- 选股（2026H1 全市场）：茅台市占 86.5%（白酒）/ 新易盛 SGR 65% / 低估榜=银行 / 东方财富净利率 76.8%
- 股息率榜单时长：冀中能源 5/9 年居首（周期高股息）；累计股息率：三钢闽光 146%（分红厚+股价深跌）

## 七、性能优化记录

- timing 历史信号扫描：O(n²) → O(n)（预计算 EMA/RSI），5748 根 K 线 46.9s → 0.06s（**780 倍**）
- 全平台受益：任何长历史标的的择时/雷达/回测

## 八、待办

1. **美股选股器**：需全市场美股估值源（东财美股行情无 PE/市值字段；Yahoo 境外）——本机评估 stock_us_spot_em 完整字段后实现 lowval 变体
2. 币质押收益/通胀率：链上数据接入（Phase 3）
3. 美股财务历史回填（backfill_us_financial）
4. 用户本机验证项：CoinGecko 代币经济 / 东财美股市值（沙箱境外/东财域受限，本机直连通常可用）

## 九、合规声明

平台仅用于行情监控与量化研究，不构成投资建议；国内使用注意
数字货币数据源跨境访问的政策边界；所有投资决策需独立判断。
