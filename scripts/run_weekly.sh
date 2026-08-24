#!/usr/bin/env bash
# 每周任务（周日 20:00）：止损/熔断风控 + 周报 + 净值 + 周度净值报告
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/Scripts/python.exe}"
CFG="--config config.local.yaml"
OUT="output/weekly"
mkdir -p "$OUT"

echo "[weekly] $(date '+%Y-%m-%d %H:%M') 开始"
# 1. 止损检查（-15%）
"$PY" -m ashare_monitor.main $CFG strategy risk 2>/dev/null | tail -10 || true
# 2. 组合熔断（-20%）
"$PY" -m ashare_monitor.main $CFG strategy breaker 2>/dev/null | tail -3 || true
# 3. 多视角周报
"$PY" -m ashare_monitor.main $CFG period --period weekly 2>/dev/null | tail -5 || true
# 4. 净值跟踪
"$PY" -m ashare_monitor.main $CFG strategy track 2>/dev/null | tail -3 || true
# 5. 周度净值报告（HTML 落盘归档）
"$PY" -m ashare_monitor.main $CFG strategy navreport 2>/dev/null | tail -2 || true
# 归档最新净值报告
if [ -f output/paper-nav-*.html ]; then
  cp -f output/paper-nav-*.html "$OUT/paper-nav-$(date '+%Y%m%d').html" 2>/dev/null || true
  echo "[weekly] 周度净值报告 → $OUT/paper-nav-$(date '+%Y%m%d').html"
fi
echo "[weekly] 完成 $(date '+%H:%M')"
