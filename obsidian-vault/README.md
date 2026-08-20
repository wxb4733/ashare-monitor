# A 股监控知识库

由 [ashare-monitor](https://github.com/wxb4733/ashare-monitor) 自动维护的独立 Obsidian 库。

## 目录

- `A股复盘/`：每日复盘报告（Markdown，自动导出）
- `模板/`：复盘笔记模板

## 复盘索引

<!-- INDEX_START -->
- [[A股复盘/review-2026-08-20|复盘 2026-08-20]]
<!-- INDEX_END -->


<!-- REPORT_INDEX_START -->
- [[汇总报告/report-monthly-2026-08-20|月报 2026-08-20]]
- [[汇总报告/report-weekly-2026-08-20|周报 2026-08-20]]
- [[汇总报告/report-yearly-2026-08-20|年报 2026-08-20]]
<!-- REPORT_INDEX_END -->
## 说明

- 每日收盘后运行 `python -m ashare_monitor.main review` 自动生成并导出复盘
- 复盘包含：大盘指数、技术指标、当日表现、预警、财报速览、公告与研报、近期 IPO
- K 线图（ECharts）以链接指向 HTML 报告
- 数据仅供学习与技术研究，不构成投资建议
