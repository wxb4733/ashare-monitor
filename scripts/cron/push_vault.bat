@echo off
rem usage: call push_vault.bat <tag>
rem notes vault -> github.com:wxb4733/obsidian-vault (personal notes only)
setlocal
set TAG=%1
if "%TAG%"=="" set TAG=manual
set PY=E:\github\ashare-monitor\.venv\Scripts\python.exe
set SCRIPT=E:\github\ashare-monitor\scripts\vault_push.py
set VLOG=E:\github\ashare-monitor\logs\cron_vault_push_notes.log
echo === %DATE% %TIME% vault push notes tag=%TAG% === >> "%VLOG%"
"%PY%" "%SCRIPT%" --repo notes --tag "%TAG%" >> "%VLOG%" 2>&1
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo [WARN] notes vault push failed rc=%RC% >> "%VLOG%"
endlocal & exit /b %RC%
