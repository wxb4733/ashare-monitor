@echo off
rem Signal digest after close-data backfill (runs after backfill 15:35).
rem Push: uncomment the next line and set a WeCom/DingTalk bot URL to enable.
rem set ASHARE_MONITOR_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=XXXX
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set LOG=E:\github\ashare-monitor\logs\cron_signal_digest.log
echo === %DATE% %TIME% signal-digest start === >> %LOG%
"E:\github\ashare-monitor\.venv\Scripts\python.exe" E:\github\ashare-monitor\scripts\signal_digest.py >> %LOG% 2>&1
echo === %DATE% %TIME% signal-digest done === >> %LOG%
