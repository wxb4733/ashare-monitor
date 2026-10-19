"""Obsidian vault 分仓推送。

两个独立仓库，同一台机器、同一个 vault 目录树：

- ``invest`` -> ``E:\\Obsidian\\wxb4733\\ashare-monitor 库``  -> github.com:wxb4733/obsidian-invest
- ``notes``  -> ``E:\\Obsidian\\wxb4733``                     -> github.com:wxb4733/obsidian-vault

拆分背景（2026-10-19）：原先 ``push_vault.bat`` 在 vault 根 ``git add -A``，把投研产出
（6,141 文件的每日复盘/周报/月报）和个人笔记（小说/购房/家庭等）混在一条提交里推到
同一分支；同时 obsidian-git 插件每 15 分钟也会对根仓库 add -A，两条通道互相
non-fast-forward（10-17/10-18 连续被拒）。拆成两仓后：投研走本脚本的 invest 分支，
个人笔记交给插件/notes 通道，互不干扰。

设计约束：bat 必须纯 ASCII（GBK 代码页会吞 CR），而投研目录名含中文，所以路径与
git 操作放在本 Python 脚本里，bat 只做 ASCII 路径转发。

用法::

    python scripts/vault_push.py --repo invest --tag close_review
    python scripts/vault_push.py --repo notes  --tag manual

退出码：0 成功（含无变更）、1 推送失败、2 参数或环境错误。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime

GIT = os.environ.get("ASHARE_GIT_EXE", r"C:\Program Files\Git\cmd\git.exe")

REPOS = {
    "invest": r"E:\Obsidian\wxb4733\ashare-monitor 库",
    "notes": r"E:\Obsidian\wxb4733",
}


def log(msg: str) -> None:
    """输出保持 ASCII，避免 GBK 控制台重定向时 UnicodeEncodeError。"""
    if not msg.isascii():
        msg = msg.encode("ascii", "replace").decode("ascii")
    print(msg, flush=True)


def run(repo: str, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        [GIT, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def rebase_in_progress(repo: str) -> bool:
    git_dir = os.path.join(repo, ".git")
    return any(
        os.path.isdir(os.path.join(git_dir, d))
        for d in ("rebase-merge", "rebase-apply")
    )


def push(repo_key: str, tag: str, branch: str = "main") -> int:
    repo = REPOS.get(repo_key)
    if not repo:
        log("ERROR: unknown repo key %r (expect invest|notes)" % repo_key)
        return 2
    if not os.path.isdir(os.path.join(repo, ".git")):
        log("ERROR: %s is not a git repository: %s" % (repo_key, repo))
        return 2
    if not os.path.isfile(GIT):
        log("ERROR: git not found at %s" % GIT)
        return 2

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log("repo=%s tag=%s" % (repo_key, tag))

    add = run(repo, "add", "-A")
    if add.returncode != 0:
        log("ERROR: git add failed: %s" % add.stderr.strip()[:400])
        return 1

    staged = run(repo, "diff", "--cached", "--quiet")
    if staged.returncode == 0:
        log("no local changes, skip commit")
    else:
        # 文件名含中文，commit message 保持 ASCII 以免跨平台编码问题
        msg = "vault sync: %s (%s)" % (tag, ts)
        c = run(repo, "commit", "-m", msg, "--no-verify")
        if c.returncode != 0:
            log("ERROR: git commit failed: %s" % (c.stderr.strip()[:400]))
            return 1
        head = run(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        files = run(repo, "show", "--stat", "--oneline", "HEAD").stdout.strip().splitlines()
        log("committed %s  %s" % (head, files[-1].strip() if files else ""))

    pull = run(repo, "pull", "--rebase", "--autostash", "origin", branch)
    if pull.returncode != 0:
        log("WARN: pull --rebase failed: %s" % pull.stderr.strip()[:400])
        if rebase_in_progress(repo):
            run(repo, "rebase", "--abort")
            log("WARN: rebase aborted to keep repo usable")

    p = run(repo, "push", "origin", branch)
    if p.returncode != 0:
        log("ERROR: push failed: %s" % p.stderr.strip()[:400])
        return 1
    local = run(repo, "rev-parse", "HEAD").stdout.strip()[:7]
    remote = run(repo, "rev-parse", "origin/%s" % branch).stdout.strip()[:7]
    log("pushed %s -> origin/%s (%s)" % (local, branch, "in sync" if local == remote else "MISMATCH"))
    return 0 if local == remote else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="push obsidian vault (split repos)")
    ap.add_argument("--repo", required=True, choices=sorted(REPOS))
    ap.add_argument("--tag", default="manual")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args(argv)
    try:
        return push(args.repo, args.tag, args.branch)
    except subprocess.TimeoutExpired as exc:
        log("ERROR: git timed out: %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
