@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE="E:\github\ashare-monitor\.venv\Scripts\ashare-monitor.exe"
set LOG=E:\github\ashare-monitor\logs\cron_dividend_weekly.log
echo === %DATE% %TIME% dividend-weekly start === >> %LOG%
%EXE% screen --metric dividend --top 30 --report >> %LOG% 2>&1
call E:\github\ashare-monitor\scripts\cron\push_vault_invest.bat dividend_weekly
echo === %DATE% %TIME% dividend-weekly done === >> %LOG%
