@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
set LOG=logs\cron_risk_check.log
echo === %DATE% %TIME% risk-check start === >> %LOG%
%EXE% strategy risk >> %LOG% 2>&1
%EXE% strategy breaker >> %LOG% 2>&1
REM 净值跟踪已由 cron_paper_daily.bat 在收盘后执行；此处盘前跑会因无行情
REM 写入 0 元 -100% 净值（2026-10-16 事故），故移除
echo === %DATE% %TIME% risk-check done === >> %LOG%
