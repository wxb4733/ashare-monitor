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


# ── 知识产权资产（智慧芽专利/论文导入） ─────────────────────

def import_ip_assets(company_name: str, patents: list | None = None,
                     papers: list | None = None,
                     db_path: str | Path | None = None) -> bool:
    """导入知识产权资产（智慧芽）：专利/论文列表 → ip_assets 表（upsert 合并）。

    :param patents: [{pn, title, date, legal_status, ...}]
    :param papers:  [{title, authors, org, date, ...}]
    """
    import sqlite3

    from .storage import get_conn

    conn = get_conn(db_path) if db_path else get_conn()
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ip_assets (
                    company TEXT PRIMARY KEY,
                    patents TEXT,
                    papers TEXT,
                    updated TEXT)""")
            row = conn.execute(
                "SELECT patents, papers FROM ip_assets WHERE company=?",
                (company_name,)).fetchone()
            old_p = json.loads(row["patents"]) if row and row["patents"] else []
            old_a = json.loads(row["papers"]) if row and row["papers"] else []
            # 合并去重（按 pn/title）
            if patents:
                seen = {p.get("pn") or p.get("title") for p in old_p}
                for p in patents:
                    key = p.get("pn") or p.get("title")
                    if key and key not in seen:
                        old_p.append(p)
                        seen.add(key)
            if papers:
                seen = {a.get("title") for a in old_a}
                for a in papers:
                    if a.get("title") and a["title"] not in seen:
                        old_a.append(a)
                        seen.add(a["title"])
            conn.execute(
                "INSERT OR REPLACE INTO ip_assets (company, patents, papers, "
                "updated) VALUES (?,?,?,?)",
                (company_name, json.dumps(old_p, ensure_ascii=False),
                 json.dumps(old_a, ensure_ascii=False),
                 __import__("datetime").datetime.now().strftime("%Y-%m-%d")))
        return True
    finally:
        conn.close()


def load_ip_assets(company_name: str,
                   db_path: str | Path | None = None) -> dict | None:
    """读取知识产权资产（无则 None）：{patents: [...], papers: [...], updated}。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn(db_path) if db_path else get_conn()
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT patents, papers, updated FROM ip_assets WHERE company=?",
            (company_name,)).fetchone()
        if not row:
            return None
        return {"patents": json.loads(row["patents"] or "[]"),
                "papers": json.loads(row["papers"] or "[]"),
                "updated": row["updated"]}
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def get_all_ip_assets(db_path: str | Path | None = None) -> dict:
    """读取全部知识产权资产：{company: {...}}。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn(db_path) if db_path else get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT company, patents, papers, updated FROM ip_assets").fetchall()
        return {r["company"]: {
            "patents": json.loads(r["patents"] or "[]"),
            "papers": json.loads(r["papers"] or "[]"),
            "updated": r["updated"]} for r in rows}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


# ── 元数据（新鲜度/血缘） ────────────────────────────

def get_profile_meta(db_path: str | Path | None = None) -> dict:
    """读取企业画像元数据：{name: {"updated": str, "source": str}}。

    用于 check 体检展示「数据血缘 + 新鲜度」。
    """
    import sqlite3

    from .storage import get_conn

    conn = get_conn(db_path) if db_path else get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT name, updated FROM company_profiles").fetchall()
        return {r["name"]: {"updated": r["updated"],
                            "source": "天眼查"} for r in rows}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def get_ip_meta(db_path: str | Path | None = None) -> dict:
    """读取知识产权元数据：{company: {"updated": str, "source": str}}。"""
    import sqlite3

    from .storage import get_conn

    conn = get_conn(db_path) if db_path else get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT company, updated FROM ip_assets").fetchall()
        return {r["company"]: {"updated": r["updated"],
                               "source": "智慧芽"} for r in rows}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
