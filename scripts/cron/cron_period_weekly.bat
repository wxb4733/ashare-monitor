@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE="E:\github\ashare-monitor\.venv\Scripts\ashare-monitor.exe"
set LOG=E:\github\ashare-monitor\logs\cron_period_weekly.log
echo === %DATE% %TIME% period-weekly start === >> %LOG%
%EXE% period --period weekly --push >> %LOG% 2>&1
call E:\github\ashare-monitor\scripts\cron\push_vault.bat period_weekly
echo === %DATE% %TIME% period-weekly done === >> %LOG%
