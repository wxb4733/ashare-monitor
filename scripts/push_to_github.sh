#!/usr/bin/env bash
# 本地推送 ashare-monitor 到 GitHub（沙箱网络受限，需本机执行）
# 用法：cd ~/github/ashare-monitor && bash scripts/push_to_github.sh
set -euo pipefail
cd "$(dirname "$0")/.."

DEFAULT_REMOTE="git@github.com:wxb4733/ashare-monitor.git"
LEGACY_REMOTE="https://github.com/wxb4733/ashare-monitor.git"
SSH_KEY=""

if command -v cygpath >/dev/null 2>&1 && [ -n "${USERPROFILE:-}" ]; then
  CANDIDATE_KEY="$(cygpath -u "$USERPROFILE/.ssh/id_ed25519_github")"
  if [ -f "$CANDIDATE_KEY" ]; then
    SSH_KEY="$CANDIDATE_KEY"
  fi
fi

echo "== 1/4 检查工作树 =="
if [ -n "$(git status -s)" ]; then
  echo "⚠️ 工作树有未提交变更，先提交或 stash：git status"
  exit 1
fi
echo "工作树干净 ✓"

echo "== 2/4 检查远程 =="
if git remote get-url origin >/dev/null 2>&1; then
  REMOTE="$(git remote get-url origin)"
  if [ "$REMOTE" = "$LEGACY_REMOTE" ]; then
    REMOTE="$DEFAULT_REMOTE"
    git remote set-url origin "$REMOTE"
  fi
else
  REMOTE="$DEFAULT_REMOTE"
  git remote add origin "$REMOTE"
fi

if [ -n "$SSH_KEY" ] && [[ "$REMOTE" == git@github.com:* ]]; then
  export GIT_SSH_COMMAND="ssh -i $SSH_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
fi

echo "origin → $REMOTE"

echo "== 3/4 推送（首次创建远程 main 分支） =="
git push -u origin main
echo "推送完成 ✓"

echo "== 4/4 验证 =="
git status -sb | head -1
echo "远程分支："
git ls-remote --heads origin | head -5
echo "完成：仓库 $REMOTE"
