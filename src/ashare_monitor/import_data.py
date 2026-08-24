"""通用外部数据导入（Wind / 天眼查等 MCP 数据源回填的落地接口）。

背景：Wind / 天眼查等数据通过 WorkBuddy MCP 连接器在会话内获取
（项目 CLI 运行时无法直接调用 MCP）——本模块提供结构化导入接口，
会话内拉取的数据以 JSON 形式落库，之后 check / 分析等命令直接读取。

能力：
    1. import_klines_json：外部 K 线 → klines 表（record_klines 幂等）
       [{date, open, close, high, low, volume}]（date 支持 yyyy-MM-dd
       或 yyyyMMdd）
    2. import_company_profile：企业画像 → company_profiles 表（新）
       {公司名: {工商/规模/标签/...}}——check 命令展示工商维度

用法（会话内）：
    from ashare_monitor.import_data import import_klines_json
    import_klines_json([...], "ashare", "002594")     # Wind K 线入库
    from ashare_monitor.import_data import import_company_profile
    import_company_profile("比亚迪股份有限公司", {...})  # 天眼查画像入库
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def import_klines_json(data: list[dict], market: str, code: str,
                       db_path: str | Path | None = None) -> int:
    """导入外部 K 线 JSON → klines 表（幂等，重复日期跳过）。

    :param data: [{date, open, close, high, low, volume}, ...]
                 date 支持 yyyy-MM-dd 或 yyyyMMdd
    :return: 新增条数
    """
    from .storage import get_conn, record_klines

    rows = []
    for r in data:
        d = str(r["date"]).replace("-", "")
        if len(d) == 8:
            d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        rows.append((d, float(r["open"]), float(r["close"]),
                     float(r["high"]), float(r["low"]),
                     float(r.get("volume") or 0)))
    conn = get_conn(db_path) if db_path else None
    try:
        return record_klines(rows, market, code,
                             db_path=db_path) if db_path else record_klines(
                                 rows, market, code)
    finally:
        if conn:
            conn.close()


def import_company_profile(company_name: str, profile: dict,
                           db_path: str | Path | None = None) -> bool:
    """导入企业画像 → company_profiles 表（公司名主键，upsert）。

    :param company_name: 企业全称（如 比亚迪股份有限公司）
    :param profile: 画像 dict（工商/规模/标签/曾用名等，JSON 序列化存储）
    """
    import sqlite3

    from .storage import get_conn

    conn = get_conn(db_path) if db_path else get_conn()
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS company_profiles (
                    name TEXT PRIMARY KEY,
                    profile TEXT,
                    updated TEXT)""")
            conn.execute(
                "INSERT OR REPLACE INTO company_profiles (name, profile, "
                "updated) VALUES (?,?,?)",
                (company_name, json.dumps(profile, ensure_ascii=False),
                 __import__("datetime").datetime.now().strftime("%Y-%m-%d")))
        return True
    finally:
        conn.close()


def load_company_profile(company_name: str,
                         db_path: str | Path | None = None) -> dict | None:
    """读取企业画像（无则 None）。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn(db_path) if db_path else get_conn()
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT profile FROM company_profiles WHERE name=?",
            (company_name,)).fetchone()
        return json.loads(row["profile"]) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def get_all_company_profiles(db_path: str | Path | None = None) -> dict:
    """读取全部企业画像：{公司全称: profile}。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn(db_path) if db_path else get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT name, profile FROM company_profiles").fetchall()
        return {r["name"]: json.loads(r["profile"]) for r in rows}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
