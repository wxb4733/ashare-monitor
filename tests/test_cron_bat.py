"""批处理脚本卫生检查。

背景：2026-09-28 起 ``cron_paper_daily.bat`` 每日静默失败 —— 注释里的 UTF-8 中文在
GBK 代码页下把行尾 CR 当作双字节字符的第二字节吃掉，导致下一行 ``cd /d`` 并入 REM，
之后所有相对路径按 ``C:\\Windows\\System32`` 解析（result=0 但什么都没做）。
``cron_paper_rebalance.bat`` 同因，从部署起从未成功调仓。

因此对 ``scripts/cron/*.bat`` 施加三条硬约束：
1. 纯 ASCII，或整文件 GBK（中文路径），不得 UTF-8 中文；
2. CRLF 换行，不得只有 LF；
3. 不出现依赖 CWD 的相对路径（.venv / logs / scripts）。
"""
from __future__ import annotations

import glob
import os
import re

import pytest

CRON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "cron")
BATS = sorted(glob.glob(os.path.join(CRON_DIR, "*.bat")))

# 引号或行首直接出现的相对路径段
REL_PATTERNS = [
    '"' + "\\" + ".venv",
    "=logs" + "\\",
    "=logs\\",
    " call scripts" + "\\",
    '"' + "\\" + "Scripts" + "\\",
]


def _read(path: str) -> tuple[bytes, str]:
    raw = open(path, "rb").read()
    try:
        return raw, raw.decode("ascii")
    except UnicodeDecodeError:
        return raw, raw.decode("gbk")  # 若不是合法 GBK 会直接抛错 → 测试失败


def test_bats_found():
    assert BATS, "scripts/cron 下没有 .bat 文件，路径可能不对"


@pytest.mark.parametrize("bat_file", BATS)
def test_encoding_is_ascii_or_gbk(bat_file):
    raw, _ = _read(bat_file)
    try:
        raw.decode("ascii")
    except UnicodeDecodeError:
        # 允许 GBK（含中文路径），但禁止 UTF-8 中文（GBK 代码页下会吞 CR）
        with pytest.raises(UnicodeDecodeError):
            raw.decode("utf-8")


@pytest.mark.parametrize("bat_file", BATS)
def test_crlf_line_endings(bat_file):
    raw, _ = _read(bat_file)
    bare_lf = raw.count(b"\n") - raw.count(b"\r\n")
    assert bare_lf == 0, f"{os.path.basename(bat_file)} 有 {bare_lf} 个裸 LF，需统一为 CRLF"


@pytest.mark.parametrize("bat_file", BATS)
def test_no_cwd_dependent_paths(bat_file):
    _, txt = _read(bat_file)
    problems = []
    for i, line in enumerate(txt.replace("\r\n", "\n").split("\n"), 1):
        s = line.strip()
        if not s or s.lower().startswith(("rem", "::", "echo", "@echo")):
            continue
        if re.search(r"(?<![A-Za-z])(?:^|\s|\")(?:\.venv|logs|scripts|output)\\", s) \
                and not re.search(r"[A-Z]:\\\\", s):
            # 已带盘符的绝对路径不算
            if not re.search(r"[A-Z]:\\", s.split(",")[0]):
                problems.append(f"L{i}: {s[:80]}")
    assert not problems, f"{os.path.basename(bat_file)} 存在依赖 CWD 的路径: {problems}"
