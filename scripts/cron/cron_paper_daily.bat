@echo off
rem Paper trading daily NAV tracking (after backfill 15:35, before signal digest 15:50).
rem NOTE: keep this file ASCII-only. UTF-8 comments broke CR parsing under GBK codepage
rem (2026-09-28..10-16: cd line merged into rem; paths resolved to C:\Windows\System32).
cd /d E:\github\ashare-monitor
if not exist "E:\github\ashare-monitor\logs" mkdir "E:\github\ashare-monitor\logs"
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=E:\github\ashare-monitor\.venv\Scripts\ashare-monitor.exe
set LOG=E:\github\ashare-monitor\logs\cron_paper_daily.log
echo === %DATE% %TIME% paper-daily start === >> "%LOG%"
"%EXE%" strategy track >> "%LOG%" 2>&1
if errorlevel 1 echo [ERROR] strategy track failed >> "%LOG%"
"%EXE%" strategy status >> "%LOG%" 2>&1
echo === %DATE% %TIME% paper-daily done === >> "%LOG%"
