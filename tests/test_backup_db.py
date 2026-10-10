"""scripts/backup_db.py 的回归测试：在线备份可读 + 保留份数裁剪。

scripts/ 不是包，按文件路径 import；测试用 tmp_path 造源库，不触碰真实 DB。
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_mod():
    spec = importlib.util.spec_from_file_location(
        "backup_db", ROOT / "scripts" / "backup_db.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_src(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE klines (market TEXT, code TEXT, date TEXT)")
    conn.execute("INSERT INTO klines VALUES ('ashare', '600519', '2026-10-09')")
    conn.commit()
    conn.close()


def test_backup_writes_readable_snapshot(tmp_path):
    mod = _load_mod()
    src = tmp_path / "src.db"
    _make_src(src)
    out = tmp_path / "out"

    dest = mod.backup(keep=14, out=str(out), src_db=src)

    assert dest.parent == out and dest.exists()
    conn = sqlite3.connect(dest)
    try:
        rows = conn.execute("SELECT market, code, date FROM klines").fetchall()
    finally:
        conn.close()
    assert rows == [("ashare", "600519", "2026-10-09")]


def test_backup_prunes_to_keep(tmp_path):
    mod = _load_mod()
    src = tmp_path / "src.db"
    _make_src(src)
    out = tmp_path / "out"
    out.mkdir()
    for stamp in ("20260101-000001", "20260102-000001", "20260103-000001"):
        (out / f"ashare_monitor.{stamp}.db").write_bytes(b"")

    mod.backup(keep=2, out=str(out), src_db=src)

    kept = sorted(p.name for p in out.glob("ashare_monitor.*.db"))
    assert len(kept) == 2
    # 最新的新备份保留；旧的中只剩名称最大的 20260103 那份
    assert any("20260103" in k for k in kept)
    assert not any("20260101" in k for k in kept)


def test_resolve_backup_dir_follows_data_symlink():
    """data 为软链时默认目录必须解链到真实数据盘，不能落在仓库根。"""
    mod = _load_mod()
    d = mod.resolve_backup_dir(None)
    assert d.name == "backup"
    assert d.parent == Path(mod.DB_PATH).resolve().parent.parent
    assert d.parent != ROOT
