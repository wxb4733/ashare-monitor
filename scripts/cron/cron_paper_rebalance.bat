@echo off
rem Dividend-rotation paper rebalance, monthly on day 1.
rem Depends on the dividend screener via eastmoney push2 (realtime domain).
rem If push2 is blocked it fails honestly and logs; it never fabricates picks.
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE="E:\github\ashare-monitor\.venv\Scripts\ashare-monitor.exe"
set LOG=E:\github\ashare-monitor\logs\cron_paper_rebalance.log
echo === %DATE% %TIME% paper-rebalance start === >> %LOG%
%EXE% strategy rebalance --paper >> %LOG% 2>&1
echo === %DATE% %TIME% paper-rebalance done === >> %LOG%
