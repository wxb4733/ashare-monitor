@echo off
REM 注册 Windows 任务计划（管理员运行）：
REM   每日 15:40  run_daily.sh（工作日，收盘后）
REM   周日 20:00  run_weekly.sh
setlocal
set ROOT=%~dp0..
set SH=%ROOT%\scripts\run_daily.sh
set SHW=%ROOT%\scripts\run_weekly.sh

schtasks /Create /F /TN "ashare-daily" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 15:40 ^
  /TR "bash %SH%" /RL LIMITED
schtasks /Create /F /TN "ashare-weekly" /SC WEEKLY /D SUN /ST 20:00 ^
  /TR "bash %SHW%" /RL LIMITED
echo 已注册：ashare-daily（工作日 15:40）/ ashare-weekly（周日 20:00）
echo 验证：schtasks /Query /TN "ashare-daily"
endlocal
