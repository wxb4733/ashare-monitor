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
# 6. 高股息池周报（队列 34 家，独立视角；缺队列文件则跳过）
if [ -f output/backfill_queue.json ]; then
  "$PY" -m ashare_monitor.main $CFG report --weekly --pool highdiv 2>/dev/null | tail -2 || true
  echo "[weekly] 高股息池周报已生成"
fi
# 7. 港股财务缓存刷新（周频幂等：中报/年报新披露自动补库，
#    本地画像优先源保持最新报告期——如 2026-06-30 中报）
for hk_code in 01211 01810; do
  "$PY" -m ashare_monitor.main backfill "$hk_code" --market hk --financial \
    2>/dev/null | grep -E "financial" | head -1 || true
done
echo "[weekly] 港股财务缓存已刷新（01211/01810）"
echo "[weekly] 完成 $(date '+%H:%M')"
