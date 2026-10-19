@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE="E:\github\ashare-monitor\.venv\Scripts\ashare-monitor.exe"
set LOG=E:\github\ashare-monitor\logs\cron_weekly_friday.log
echo === %DATE% %TIME% weekly start === >> %LOG%
%EXE% report --weekly >> %LOG% 2>&1
%EXE% events --days 7 --push >> %LOG% 2>&1
%EXE% arxiv 002594 >> %LOG% 2>&1
%EXE% arxiv 01211 >> %LOG% 2>&1
%EXE% arxiv 300750 >> %LOG% 2>&1
%EXE% arxiv 600519 >> %LOG% 2>&1
%EXE% hf 002594 >> %LOG% 2>&1
%EXE% hf 01211 >> %LOG% 2>&1
%EXE% hf 300750 >> %LOG% 2>&1
%EXE% obsidian index >> %LOG% 2>&1
call E:\github\ashare-monitor\scripts\cron\push_vault_invest.bat weekly_friday
echo === %DATE% %TIME% weekly done === >> %LOG%
