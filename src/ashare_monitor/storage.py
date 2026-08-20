"""历史复盘数据积累：SQLite 持久化。

存储路径：data/ashare_monitor.db（已 gitignore）
- alerts：每日预警明细（含波动画像）
- reviews：每日复盘报告元信息（行情快照摘要、预警统计）

提供按日期范围聚合查询，支撑周报 / 月报生成。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from .alerts import Alert
from .quotes import Quote

logger = logging.getLogger(__name__)

DB_PATH = Path("data") / "ashare_monitor.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    market TEXT DEFAULT 'ashare',
    rule TEXT,
    message TEXT,
    profile TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_date ON alerts(date);
CREATE INDEX IF NOT EXISTS idx_alerts_code ON alerts(code, date);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    generated_at TEXT NOT NULL,
    report_path TEXT,
    alert_count INTEGER DEFAULT 0,
    quotes_json TEXT,
    indexes_json TEXT
);

CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    date TEXT,
    title TEXT,
    url TEXT UNIQUE,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ann_code ON announcements(code, date);

CREATE TABLE IF NOT EXISTS research_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    date TEXT,
    title TEXT,
    org TEXT,
    eps REAL,
    pe REAL,
    url TEXT UNIQUE,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_report_code ON research_reports(code, date);
"""


def _connect(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


# ---------- 预警 ----------

def record_alerts(
    alerts: list[Alert],
    market: str = "ashare",
    db_path: str | Path = DB_PATH,
) -> int:
    """写入预警记录，返回写入条数。"""
    if not alerts:
        return 0
    conn = _connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO alerts (date, time, code, name, market, rule, message, profile) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    a.fired_at.strftime("%Y-%m-%d"),
                    a.fired_at.strftime("%H:%M:%S"),
                    a.code,
                    a.name,
                    market,
                    a.rule,
                    a.message,
                    a.profile,
                )
                for a in alerts
            ],
        )
        conn.commit()
        return len(alerts)
    finally:
        conn.close()


def load_alerts_range(
    start: str,
    end: str,
    db_path: str | Path = DB_PATH,
) -> list[dict]:
    """按日期范围查询预警（含当天，start/end 格式 YYYY-MM-DD）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT date, time, code, name, market, rule, message, profile "
            "FROM alerts WHERE date BETWEEN ? AND ? "
            "ORDER BY date, time",
            (start, end),
        ).fetchall()
        return [
            {
                "date": r[0], "time": r[1], "code": r[2], "name": r[3],
                "market": r[4], "rule": r[5], "message": r[6], "profile": r[7],
            }
            for r in rows
        ]
    finally:
        conn.close()


def count_alerts_by_rule(
    start: str,
    end: str,
    db_path: str | Path = DB_PATH,
) -> list[dict]:
    """按规则聚合预警数（降序）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT rule, COUNT(*) AS n FROM alerts "
            "WHERE date BETWEEN ? AND ? GROUP BY rule ORDER BY n DESC",
            (start, end),
        ).fetchall()
        return [{"rule": r[0], "count": r[1]} for r in rows]
    finally:
        conn.close()


def count_alerts_daily(
    start: str,
    end: str,
    db_path: str | Path = DB_PATH,
) -> list[dict]:
    """按日期聚合预警数（升序）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT date, COUNT(*) AS n FROM alerts "
            "WHERE date BETWEEN ? AND ? GROUP BY date ORDER BY date",
            (start, end),
        ).fetchall()
        return [{"date": r[0], "count": r[1]} for r in rows]
    finally:
        conn.close()


def count_alerts_by_code(
    start: str,
    end: str,
    db_path: str | Path = DB_PATH,
) -> list[dict]:
    """按代码聚合预警数（降序）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT code, name, COUNT(*) AS n FROM alerts "
            "WHERE date BETWEEN ? AND ? GROUP BY code ORDER BY n DESC",
            (start, end),
        ).fetchall()
        return [{"code": r[0], "name": r[1], "count": r[2]} for r in rows]
    finally:
        conn.close()


# ---------- 每日复盘记录 ----------

def save_review(
    date_str: str,
    report_path: str,
    quotes: list[Quote],
    records: list[dict],
    index_quotes: list[Quote] | None = None,
    db_path: str | Path = DB_PATH,
) -> None:
    """写入（或更新）某天的复盘记录。"""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO reviews (date, generated_at, report_path, alert_count, "
            "quotes_json, indexes_json) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET generated_at=excluded.generated_at, "
            "report_path=excluded.report_path, alert_count=excluded.alert_count, "
            "quotes_json=excluded.quotes_json, indexes_json=excluded.indexes_json",
            (
                date_str,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                str(report_path),
                len(records),
                json.dumps([
                    {"code": q.code, "name": q.name, "price": q.price,
                     "change_pct": q.change_pct, "amplitude": q.amplitude}
                    for q in quotes
                ], ensure_ascii=False),
                json.dumps([
                    {"code": q.code, "name": q.name, "price": q.price,
                     "change_pct": q.change_pct}
                    for q in (index_quotes or [])
                ], ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_reviews_range(
    start: str,
    end: str,
    db_path: str | Path = DB_PATH,
) -> list[dict]:
    """按日期范围查询复盘记录（升序）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT date, generated_at, report_path, alert_count, quotes_json, indexes_json "
            "FROM reviews WHERE date BETWEEN ? AND ? ORDER BY date",
            (start, end),
        ).fetchall()
        result = []
        for r in rows:
            item = {
                "date": r[0], "generated_at": r[1], "report_path": r[2],
                "alert_count": r[3],
            }
            try:
                item["quotes"] = json.loads(r[4] or "[]")
            except json.JSONDecodeError:
                item["quotes"] = []
            try:
                item["indexes"] = json.loads(r[5] or "[]")
            except json.JSONDecodeError:
                item["indexes"] = []
            result.append(item)
        return result
    finally:
        conn.close()


# ---------- 公告与研报 ----------

def record_announcements(
    items: list[dict],
    code: str,
    name: str = "",
    db_path: str | Path = DB_PATH,
) -> tuple[int, int]:
    """入库公告（url 唯一去重）。

    :return: (新增条数, 已存在条数)
    """
    if not items:
        return 0, 0
    conn = _connect(db_path)
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new = 0
        for it in items:
            cur = conn.execute(
                "INSERT OR IGNORE INTO announcements (code, name, date, title, url, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (code, name or "", it.get("date", ""), it.get("title", ""),
                 it.get("url", ""), now),
            )
            new += cur.rowcount
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM announcements WHERE code=?", (code,)).fetchone()[0]
        return new, max(total - new, 0)
    finally:
        conn.close()


def load_announcements(
    code: str,
    limit: int = 30,
    db_path: str | Path = DB_PATH,
) -> list[dict]:
    """查询某标的入库公告（按日期倒序）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT code, name, date, title, url FROM announcements "
            "WHERE code=? ORDER BY date DESC, id DESC LIMIT ?",
            (code[-6:], limit),
        ).fetchall()
        return [
            {"code": r[0], "name": r[1], "date": r[2], "title": r[3], "url": r[4]}
            for r in rows
        ]
    finally:
        conn.close()


def record_research_reports(
    items: list[dict],
    code: str,
    name: str = "",
    db_path: str | Path = DB_PATH,
) -> tuple[int, int]:
    """入库研报（url 唯一去重）。

    :return: (新增条数, 已存在条数)
    """
    if not items:
        return 0, 0
    conn = _connect(db_path)
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new = 0
        for it in items:
            cur = conn.execute(
                "INSERT OR IGNORE INTO research_reports "
                "(code, name, date, title, org, eps, pe, url, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (code, name or "", it.get("date", ""), it.get("title", ""),
                 it.get("org", ""), it.get("eps_this_year"), it.get("pe_this_year"),
                 it.get("url", ""), now),
            )
            new += cur.rowcount
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM research_reports WHERE code=?", (code,)).fetchone()[0]
        return new, max(total - new, 0)
    finally:
        conn.close()


def load_research_reports(
    code: str,
    limit: int = 30,
    db_path: str | Path = DB_PATH,
) -> list[dict]:
    """查询某标的入库研报（按日期倒序）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT code, name, date, title, org, eps, pe, url FROM research_reports "
            "WHERE code=? ORDER BY date DESC, id DESC LIMIT ?",
            (code[-6:], limit),
        ).fetchall()
        return [
            {"code": r[0], "name": r[1], "date": r[2], "title": r[3],
             "org": r[4], "eps_this_year": r[5], "pe_this_year": r[6], "url": r[7]}
            for r in rows
        ]
    finally:
        conn.close()


def count_news_by_code(db_path: str | Path = DB_PATH) -> list[dict]:
    """统计各标的入库的公告/研报条数（按公告+研报总数降序）。"""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT code, "
            "(SELECT COUNT(*) FROM announcements a WHERE a.code = n.code) AS anns, "
            "(SELECT COUNT(*) FROM research_reports r WHERE r.code = n.code) AS reps "
            "FROM (SELECT DISTINCT code FROM announcements "
            "      UNION SELECT DISTINCT code FROM research_reports) n "
            "ORDER BY (anns + reps) DESC",
        ).fetchall()
        return [{"code": r[0], "anns": r[1], "reports": r[2]} for r in rows]
    finally:
        conn.close()
