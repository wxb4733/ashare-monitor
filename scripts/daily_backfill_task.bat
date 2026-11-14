@echo off
REM ashare-monitor daily data accumulation (schtasks: 15:35 after A-share close)
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
echo === %DATE% %TIME% daily task start === >> logs\backfill_task.log 2>&1
REM 1) K-line incremental for all watchlist
%EXE% backfill_kline >> logs\backfill_task.log 2>&1
REM 1b) K-line incremental for ALL tracked ashare/hk codes (watchlist + dividend queue)
REM     (2026-10-16 add: queue codes were no longer covered by step 1)
".venv\Scripts\python.exe" scripts\backfill_kline_all.py >> logs\backfill_task.log 2>&1
REM 2) news/financial incremental for A-share watchlist
REM    (--news --financial: K-line already handled by step 1, so skip the
REM     full-history kline re-pull this used to trigger every day)
%EXE% backfill 600519 --news --financial >> logs\backfill_task.log 2>&1
%EXE% backfill 000001 --news --financial >> logs\backfill_task.log 2>&1
%EXE% backfill 300750 --news --financial >> logs\backfill_task.log 2>&1
%EXE% backfill 002594 --news --financial >> logs\backfill_task.log 2>&1
REM 2b) HK announcements (no daily coverage before 2026-10-16; caused 01211/01810 lag)
%EXE% backfill 01211 --market hk --news >> logs\backfill_task.log 2>&1
%EXE% backfill 01810 --market hk --news >> logs\backfill_task.log 2>&1
REM 3) review HTML + Obsidian markdown export (to real vault)
%EXE% review >> logs\backfill_task.log 2>&1
REM 4) push invest vault (review markdown export) to GitHub (obsidian-invest repo)
REM    (2026-11-14 fix: legacy step pushed the notes repo and was rejected every
REM     day since the vault split; review MD now lives in the invest repo)
call E:\github\ashare-monitor\scripts\cron\push_vault_invest.bat daily_backfill
cd /d E:\github\ashare-monitor
REM 5) DB rolling backup (online backup API, keep newest 14)
".venv\Scripts\python.exe" scripts\backup_db.py --keep 14 >> logs\backup.log 2>&1
echo === %DATE% %TIME% daily task done === >> logs\backfill_task.log 2>&1
