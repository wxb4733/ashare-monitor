@echo off
rem 高胜率信号日报：收盘数据回补后运行（backfill 15:35 完成后）
rem 推送：取消下一行注释并填入企业微信/钉钉机器人地址后启用推送
rem set ASHARE_MONITOR_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=XXXX
cd /d E:\github\ashare-monitor
set NO_PROXY=eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn
set LOG=logs\cron_signal_digest.log
echo === %DATE% %TIME% signal-digest start === >> %LOG%
".venv\Scripts\python.exe" scripts\signal_digest.py >> %LOG% 2>&1
echo === %DATE% %TIME% signal-digest done === >> %LOG%
