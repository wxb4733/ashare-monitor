"""数据库滚动备份：sqlite3 online backup API 落盘 + 保留最近 N 份。

- 用 Connection.backup()（在线备份 API），有并发写时也能拿到一致快照，
  不用 cp/copy 直接拷文件（可能拷到写到一半的页）。
- 落到 data/../backup（默认 E:\\database\\backup，与 DB 同盘便于整体搬迁）。
- 默认保留最近 14 份，超出按文件名日期倒序删除。

用法：python scripts/backup_db.py [--keep 14] [--out DIR]
定时：scripts/daily_backfill_task.bat 步骤 5（每日收盘任务末尾）。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare_monitor.storage import DB_PATH  # noqa: E402


def resolve_backup_dir(out: str | None) -> Path:
    """默认 DB 同理的 backup 目录。

    注意：DB_PATH 是相对路径（data/ashare_monitor.db），而 data 是指向
    真实数据盘（E:\\database\\sqlite）的软链——必须先 resolve() 解链，
    否则会误建到仓库根目录下。
    """
    if out:
        return Path(out)
    db = Path(DB_PATH)
    if not db.is_absolute():
        db = ROOT / db
    return db.resolve().parent.parent / "backup"


def backup(keep: int = 14, out: str | None = None,
           src_db: str | Path | None = None) -> Path:
    target_dir = resolve_backup_dir(out)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = target_dir / f"ashare_monitor.{stamp}.db"

    source = Path(src_db) if src_db else Path(DB_PATH)
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()

    size_mb = dest.stat().st_size / 1024 / 1024
    print(f"DB 备份完成: {dest}（{size_mb:.2f} MB）")

    old = sorted((p for p in target_dir.glob("ashare_monitor.*.db")
                  if p != dest), key=lambda p: p.name, reverse=True)
    for p in old[max(keep - 1, 0):]:
        p.unlink()
        print(f"  清理旧备份: {p.name}")
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description="ashare-monitor DB 滚动备份")
    ap.add_argument("--keep", type=int, default=14, help="保留份数（默认 14）")
    ap.add_argument("--out", default=None, help="备份目录（默认 DB 同级 backup）")
    args = ap.parse_args()
    backup(keep=args.keep, out=args.out)


if __name__ == "__main__":
    main()
