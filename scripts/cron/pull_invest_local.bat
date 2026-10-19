@echo off
rem usage: called by schtasks task "ashare_vault_invest_pull"
rem pulls obsidian-invest subrepo on this machine (CJK path handled inside python)
setlocal
set PY=C:\Users\Administrator\github\ashare-monitor\.venv\Scripts\python.exe
set SCRIPT=C:\Users\Administrator\github\ashare-monitor\scripts\invest_pull_local.py
"%PY%" "%SCRIPT%"
endlocal & exit /b %ERRORLEVEL%
