#!/usr/bin/env bash
# 每日任务：盘中监控 + 日报 + 模拟净值跟踪（工作日 15:30 后运行）
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/Scripts/python.exe}"
CFG="--config config.local.yaml"

echo "[daily] $(date '+%Y-%m-%d %H:%M') 开始"
# 1. 盘中异动监控（收盘后跑当日信号）
"$PY" -m ashare_monitor.main $CFG monitor 2>/dev/null | tail -20 || true
# 2. 多视角日报（四市场）
"$PY" -m ashare_monitor.main $CFG period --period daily 2>/dev/null | tail -5 || true
# 3. 模拟组合净值记录（paper_history 积累）
"$PY" -m ashare_monitor.main $CFG strategy track 2>/dev/null | tail -3 || true
echo "[daily] 完成 $(date '+%H:%M')"
