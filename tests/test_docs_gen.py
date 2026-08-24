"""命令自动文档生成测试。"""


def test_generate_commands_md():
    from ashare_monitor.docs_gen import generate_commands_md

    md = generate_commands_md()
    assert "# ashare-monitor 命令参考" in md
    assert "## 命令总览" in md and "## 命令详情" in md
    # 核心命令全覆盖
    for cmd in ("check", "screen", "strategy", "backfill", "history",
                "period", "ad", "monitor", "radar"):
        assert f"`{cmd}`" in md
    # check 参数表含 --market
    check_sec = md.split("### check")[1].split("### ")[0]
    assert "| code |" in check_sec
    assert "--market" in check_sec


def test_write_commands_md(tmp_path):
    from ashare_monitor.docs_gen import write_commands_md

    path = write_commands_md(str(tmp_path / "cmd.md"))
    content = open(path, encoding="utf-8").read()
    assert "共 " in content and "个命令" in content
