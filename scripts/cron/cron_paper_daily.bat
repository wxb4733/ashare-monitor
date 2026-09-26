@echo off
rem 模拟盘每日净值跟踪（backfill 15:35 之后、信号日报 15:50 之前）
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
set LOG=logs\cron_paper_daily.log
echo === %DATE% %TIME% paper-daily start === >> %LOG%
%EXE% strategy track >> %LOG% 2>&1
%EXE% strategy status >> %LOG% 2>&1
echo === %DATE% %TIME% paper-daily done === >> %LOG%
