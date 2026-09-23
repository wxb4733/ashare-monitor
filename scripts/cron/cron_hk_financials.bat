@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE=".venv\Scripts\ashare-monitor.exe"
set LOG=logs\cron_hk_financials.log
echo === %DATE% %TIME% hk-financials start === >> %LOG%
%EXE% backfill 01211 --market hk --financial >> %LOG% 2>&1
%EXE% backfill 01810 --market hk --financial >> %LOG% 2>&1
echo === %DATE% %TIME% hk-financials done === >> %LOG%
