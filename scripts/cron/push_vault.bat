@echo off
REM usage: call push_vault.bat <tag>
set VLOG=E:\github\ashare-monitor\logs\cron_vault_push.log
cd /d E:\Obsidian\wxb4733
"C:\Program Files\Git\cmd\git.exe" add -A >> %VLOG% 2>&1
"C:\Program Files\Git\cmd\git.exe" diff --cached --quiet
if errorlevel 1 "C:\Program Files\Git\cmd\git.exe" commit -m "vault sync: %1 (%DATE% %TIME%)" >> %VLOG% 2>&1
"C:\Program Files\Git\cmd\git.exe" push origin main >> %VLOG% 2>&1
cd /d E:\github\ashare-monitor
