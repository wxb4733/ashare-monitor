@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
set LOG=logs\cron_period_daily.log
echo === %DATE% %TIME% period-daily start === >> %LOG%
%EXE% period --period daily --push >> %LOG% 2>&1
call scripts\cron\push_vault.bat period_daily
echo === %DATE% %TIME% period-daily done === >> %LOG%
