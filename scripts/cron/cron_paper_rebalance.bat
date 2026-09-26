@echo off
rem 股息轮动模拟盘月度调仓（每月 1 日）：
rem 依赖高股息全市场选股（东财 push2 实时域）。push2 受阻期间会如实失败并落日志，
rem 不伪造选股结果；恢复后自动换用真实筛选结果。
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
set LOG=logs\cron_paper_rebalance.log
echo === %DATE% %TIME% paper-rebalance start === >> %LOG%
%EXE% strategy rebalance --paper >> %LOG% 2>&1
echo === %DATE% %TIME% paper-rebalance done === >> %LOG%
