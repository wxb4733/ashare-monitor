@echo off
REM ashare-monitor daily data accumulation (schtasks: 15:35 after A-share close)
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
echo === %DATE% %TIME% daily task start === >> logs\backfill_task.log 2>&1
REM 1) K-line incremental for all watchlist
%EXE% backfill_kline >> logs\backfill_task.log 2>&1
REM 2) news/financial incremental for A-share watchlist
REM    (--news --financial: K-line already handled by step 1, so skip the
REM     full-history kline re-pull this used to trigger every day)
%EXE% backfill 600519 --news --financial >> logs\backfill_task.log 2>&1
%EXE% backfill 000001 --news --financial >> logs\backfill_task.log 2>&1
%EXE% backfill 300750 --news --financial >> logs\backfill_task.log 2>&1
%EXE% backfill 002594 --news --financial >> logs\backfill_task.log 2>&1
REM 3) review HTML + Obsidian markdown export (to real vault)
%EXE% review >> logs\backfill_task.log 2>&1
REM 4) push vault accumulation to GitHub (obsidian-vault repo)
cd /d E:\Obsidian\wxb4733
"C:\Program Files\Git\cmd\git.exe" add -A >> E:\github\ashare-monitor\logs\backfill_task.log 2>&1
"C:\Program Files\Git\cmd\git.exe" diff --cached --quiet
if errorlevel 1 "C:\Program Files\Git\cmd\git.exe" commit -m "vault sync: daily review auto-commit (%DATE%)" >> E:\github\ashare-monitor\logs\backfill_task.log 2>&1
"C:\Program Files\Git\cmd\git.exe" push origin main >> E:\github\ashare-monitor\logs\backfill_task.log 2>&1
cd /d E:\github\ashare-monitor
REM 5) DB rolling backup (online backup API, keep newest 14)
".venv\Scripts\python.exe" scripts\backup_db.py --keep 14 >> logs\backup.log 2>&1
echo === %DATE% %TIME% daily task done === >> logs\backfill_task.log 2>&1
