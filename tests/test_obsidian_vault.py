"""独立 Obsidian 知识库管理单元测试。"""

from ashare_monitor.obsidian_vault import build_vault_index, init_vault


def test_init_vault_structure(tmp_path):
    root = init_vault(tmp_path / "vault")
    assert (root / ".obsidian" / "app.json").exists()
    assert (root / ".obsidian" / "core-plugins.json").exists()
    assert (root / ".obsidian" / "templates.json").exists()
    assert (root / "A股复盘").is_dir()
    assert (root / "模板" / "复盘模板.md").exists()
    assert (root / "README.md").exists()
    assert (root / ".gitignore").exists()
    # 首页含索引占位
    home = (root / "README.md").read_text(encoding="utf-8")
    assert "<!-- INDEX_START -->" in home and "<!-- INDEX_END -->" in home
    assert "（暂无复盘记录" in home


def test_init_vault_idempotent(tmp_path):
    root = init_vault(tmp_path / "vault")
    home = (root / "README.md").read_text(encoding="utf-8")
    init_vault(tmp_path / "vault")   # 重复执行不覆盖
    assert (root / "README.md").read_text(encoding="utf-8") == home


def test_build_vault_index_with_reports(tmp_path):
    root = init_vault(tmp_path / "vault")
    (root / "A股复盘" / "review-2026-08-19.md").write_text("# 复盘", encoding="utf-8")
    (root / "A股复盘" / "review-2026-08-20.md").write_text("# 复盘", encoding="utf-8")
    (root / "A股复盘" / "notes-2026-08-20.md").write_text("# 笔记", encoding="utf-8")

    build_vault_index(root)
    home = (root / "README.md").read_text(encoding="utf-8")
    # 只索引复盘文件，按名称排序
    assert "[[A股复盘/review-2026-08-19|复盘 2026-08-19]]" in home
    assert "[[A股复盘/review-2026-08-20|复盘 2026-08-20]]" in home
    assert "notes-2026-08-20" not in home
    # 索引在占位符之间
    start = home.index("<!-- INDEX_START -->")
    end = home.index("<!-- INDEX_END -->")
    assert "review-2026-08-19" in home[start:end]
    # 幂等：再次更新不重复累积
    build_vault_index(root)
    home2 = (root / "README.md").read_text(encoding="utf-8")
    assert home2.count("review-2026-08-19") == 1
