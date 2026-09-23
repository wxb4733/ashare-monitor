@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
set LOG=logs\cron_period_monthly.log
echo === %DATE% %TIME% monthly guard === >> %LOG%
".venv\Scripts\python.exe" -c "import calendar,datetime,sys;t=datetime.date.today();sys.exit(0 if t.day==calendar.monthrange(t.year,t.month)[1] else 1)"
if errorlevel 1 (
  echo not month-end, skip >> %LOG%
  exit /b 0
)
%EXE% period --period monthly --push >> %LOG% 2>&1
call scripts\cron\push_vault.bat period_monthly
echo === %DATE% %TIME% monthly done === >> %LOG%
