@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE="E:\github\ashare-monitor\.venv\Scripts\ashare-monitor.exe"
set LOG=E:\github\ashare-monitor\logs\cron_period_daily.log
echo === %DATE% %TIME% period-daily start === >> %LOG%
%EXE% period --period daily --push >> %LOG% 2>&1
call E:\github\ashare-monitor\scripts\cron\push_vault_invest.bat period_daily
echo === %DATE% %TIME% period-daily done === >> %LOG%
