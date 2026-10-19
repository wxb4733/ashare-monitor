# -*- coding: utf-8 -*-
"""本机投研子仓库定时拉取（obsidian-invest）。

本机（ThinkPad X1C）vault 位于 D:\\Obsidian\\wxb4733，而拆分/推送机器的
vault 位于 E:\\Obsidian\\wxb4733（vault_push.py 硬编码）。本脚本只做 PULL，
把拆分机器推送的收盘复盘/日报周报等新报告同步到本机 Obsidian。

调度：schtasks 任务 ashare_vault_invest_pull（见 scripts/cron/pull_invest_local.bat）
日志：logs/cron_invest_pull_local.log
"""
import datetime as dt
import os
import subprocess
import sys

INVEST_REPO = r"D:\Obsidian\wxb4733\ashare-monitor 库"
LOG = r"C:\Users\Administrator\github\ashare-monitor\logs\cron_invest_pull_local.log"
ACTIVE_HOURS = (7, 23)  # 07:00-23:59 之外跳过，避免深夜空转


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # 日志写失败不影响主流程


def main() -> int:
    hour = dt.datetime.now().hour
    if not (ACTIVE_HOURS[0] <= hour <= ACTIVE_HOURS[1]):
        log("skip: outside active window 07-23")
        return 0

    # schtasks 拉起的环境 PATH 里第一个 ssh 是 WorkBuddy 便携版（MSYS home 损坏，
    # 报 Host key verification failed / publickey denied）。修复方式：
    # 子仓库已配置 core.sshCommand 指向 Git 自带 ssh + 显式密钥/known_hosts 绝对
    # 路径，不依赖 PATH 和 HOME；这里仅固化 HOME 作为兜底，不再设置
    # GIT_SSH_COMMAND（它会覆盖仓库级 core.sshCommand）。
    env = os.environ.copy()
    env["HOME"] = os.environ.get("USERPROFILE", r"C:\Users\Administrator")
    log(f"env HOME={env.get('HOME')!r}")

    r = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=INVEST_REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode == 0:
        # up to date 时 git 把提示写到 stderr，输出压缩到一行
        brief = " ".join(out.split())[:200]
        log(f"pull ok: {brief if brief else '(no output)'}")
        return 0
    log(f"pull FAILED rc={r.returncode}: {' '.join(out.split())[:300]}")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
