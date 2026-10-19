@echo off
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set EXE="E:\github\ashare-monitor\.venv\Scripts\ashare-monitor.exe"
set LOG=E:\github\ashare-monitor\logs\cron_scan.log
echo === %DATE% %TIME% scan start === >> %LOG%
%EXE% scan >> %LOG% 2>&1
echo === %DATE% %TIME% scan done === >> %LOG%
