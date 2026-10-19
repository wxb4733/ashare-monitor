@echo off
rem usage: call push_vault_invest.bat <tag>
rem invest vault -> github.com:wxb4733/obsidian-invest (CJK path handled inside python)
setlocal
set TAG=%1
if "%TAG%"=="" set TAG=manual
set PY=E:\github\ashare-monitor\.venv\Scripts\python.exe
set SCRIPT=E:\github\ashare-monitor\scripts\vault_push.py
set VLOG=E:\github\ashare-monitor\logs\cron_vault_push_invest.log
echo === %DATE% %TIME% vault push invest tag=%TAG% === >> "%VLOG%"
"%PY%" "%SCRIPT%" --repo invest --tag "%TAG%" >> "%VLOG%" 2>&1
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo [WARN] invest vault push failed rc=%RC% >> "%VLOG%"
endlocal & exit /b %RC%
