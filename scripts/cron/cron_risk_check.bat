@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
set LOG=logs\cron_risk_check.log
echo === %DATE% %TIME% risk-check start === >> %LOG%
%EXE% strategy risk >> %LOG% 2>&1
%EXE% strategy breaker >> %LOG% 2>&1
%EXE% strategy track >> %LOG% 2>&1
echo === %DATE% %TIME% risk-check done === >> %LOG%
