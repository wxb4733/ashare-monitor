@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
set LOG=logs\cron_nav_weekly.log
echo === %DATE% %TIME% nav-weekly start === >> %LOG%
%EXE% strategy navreport >> %LOG% 2>&1
if not exist "E:\Obsidian\wxb4733\ashare-monitor ¿â\nav_reports" mkdir "E:\Obsidian\wxb4733\ashare-monitor ¿â\nav_reports"
copy /Y output\paper-nav-*.html "E:\Obsidian\wxb4733\ashare-monitor ¿â\nav_reports\" >> %LOG% 2>&1
call scripts\cron\push_vault.bat nav_weekly
echo === %DATE% %TIME% nav-weekly done === >> %LOG%
