@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE="E:\github\ashare-monitor\.venv\Scripts\ashare-monitor.exe"
set LOG=E:\github\ashare-monitor\logs\cron_risk_check.log
echo === %DATE% %TIME% risk-check start === >> %LOG%
%EXE% strategy risk >> %LOG% 2>&1
%EXE% strategy breaker >> %LOG% 2>&1
rem NAV tracking moved to cron_paper_daily.bat (after close).
rem Running before the open produces a bogus -100% NAV (2026-10-16 incident), so removed.
echo === %DATE% %TIME% risk-check done === >> %LOG%
