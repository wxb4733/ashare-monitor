@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
set LOG=logs\cron_close_review.log
echo === %DATE% %TIME% close-review start === >> %LOG%
%EXE% review >> %LOG% 2>&1
%EXE% timing --push >> %LOG% 2>&1
%EXE% position --push >> %LOG% 2>&1
%EXE% news --watchlist --days 30 >> %LOG% 2>&1
%EXE% obsidian index >> %LOG% 2>&1
call scripts\cron\push_vault.bat close_review
echo === %DATE% %TIME% close-review done === >> %LOG%
