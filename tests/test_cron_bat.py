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


REPO_ROOT = CRON_DIR.rsplit(os.sep + "scripts", 1)[0]


def _git_index_blob(path: str) -> bytes | None:
    """取该文件在 git 索引中的原始字节；git 不可用/未入库时返回 None。"""
    import subprocess

    rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
    try:
        out = subprocess.run(["git", "-C", REPO_ROOT, "show", f":{rel}"],
                             capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


@pytest.mark.parametrize("bat_file", BATS)
def test_bat_blob_keeps_crlf(bat_file):
    """仓库 blob 也必须是 CRLF（.gitattributes 的 *.bat -text 不得被改回）。

    背景：2026-10-19 提交 3c6ab75 把 17 个 bat 存成 LF，工作区当时也是 LF，
    cmd.exe 解析错乱使 cron_paper_daily 的 strategy track 参数变形报错，
    10-19 净值漏写。仅校验工作区（上面的 test_crlf_line_endings）不够——
    提交动作本身才是污染源，故直接查索引 blob。
    """
    blob = _git_index_blob(bat_file)
    if blob is None:
        pytest.skip("git 不可用或文件尚未入库")
    bare_lf = blob.count(b"\n") - blob.count(b"\r\n")
    assert bare_lf == 0, (
        f"{os.path.basename(bat_file)} 仓库 blob 有 {bare_lf} 个裸 LF；"
        f"请确认 .gitattributes 中 *.bat 为 -text 并重新 git add")


@pytest.mark.parametrize("bat_file", BATS)
def test_no_double_quoted_exe_var(bat_file):
    """禁止 "%EXE%" 写法：变量值已含引号，再包一层会展开成 ""prog""，
    cmd 把 strategy track 等参数拼成单个带空格参数导致 argparse 报
    invalid choice（2026-10-20/21 cron_paper_daily 连续两日净值漏写根因，
    此前误诊为 LF 行尾）。统一写 %EXE%（引号在 set 行内）。"""
    with open(bat_file, "r", encoding="ascii", errors="replace") as f:
        text = f.read()
    for i, line in enumerate(text.splitlines(), 1):
        assert '"%EXE%"' not in line, (
            f"{os.path.basename(bat_file)} 第 {i} 行使用了 \"%EXE%\" 双重引号写法："
            f"{line.strip()!r}；EXE 的 set 行已含引号，请直接写 %EXE%")
