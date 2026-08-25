@echo off
REM ============================================================
REM 注册 ashare-monitor Windows 计划任务（需管理员权限）
REM   每日 15:40（周一~周五）：run_daily.cmd  → 收盘后行情/预警/复盘/净值
REM   周日 20:00            ：run_weekly.cmd → 周度风控/周报/净值报告
REM
REM 用法：右键本文件 →「以管理员身份运行」
REM 验证：schtasks /Query /TN "ashare-daily"
REM ============================================================
setlocal
set "ROOT=C:\Users\Administrator\github\ashare-monitor"
set "TASK_DAILY=%ROOT%\scripts\run_daily.cmd"
set "TASK_WEEKLY=%ROOT%\scripts\run_weekly.cmd"

echo [1/2] 注册每日任务 ashare-daily（工作日 15:40）...
schtasks /Create /F /TN "ashare-daily" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 15:40 ^
  /TR "%TASK_DAILY%" /RL LIMITED
if errorlevel 1 (
  echo [错误] ashare-daily 注册失败，请确认以管理员身份运行
  pause
  exit /b 1
)

echo [2/2] 注册每周任务 ashare-weekly（周日 20:00）...
schtasks /Create /F /TN "ashare-weekly" /SC WEEKLY /D SUN /ST 20:00 ^
  /TR "%TASK_WEEKLY%" /RL LIMITED
if errorlevel 1 (
  echo [错误] ashare-weekly 注册失败，请确认以管理员身份运行
  pause
  exit /b 1
)

echo.
echo 注册完成，验证结果：
schtasks /Query /TN "ashare-daily" /FO LIST | findstr /i "TaskName Next Status"
schtasks /Query /TN "ashare-weekly" /FO LIST | findstr /i "TaskName Next Status"
echo.
echo 提示：若任务未自动触发，请检查任务计划程序中的「运行用户」与「仅在用户登录时运行」设置。
endlocal
pause
