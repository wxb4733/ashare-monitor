#!/usr/bin/env bash
# 本地推送 ashare-monitor 到 GitHub（沙箱网络受限，需本机执行）
# 用法：cd ~/github/ashare-monitor && bash scripts/push_to_github.sh
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE="https://github.com/wxb4733/ashare-monitor.git"

echo "== 1/4 检查工作树 =="
if [ -n "$(git status -s)" ]; then
  echo "⚠️ 工作树有未提交变更，先提交或 stash：git status"
  exit 1
fi
echo "工作树干净 ✓"

echo "== 2/4 检查远程 =="
git remote set-url origin "$REMOTE" 2>/dev/null || git remote add origin "$REMOTE"
echo "origin → $REMOTE"

echo "== 3/4 推送（首次创建远程 main 分支） =="
git push -u origin main
echo "推送完成 ✓"

echo "== 4/4 验证 =="
git status -sb | head -1
echo "远程分支："
git ls-remote --heads origin | head -5
echo "完成：仓库 https://github.com/wxb4733/ashare-monitor"
