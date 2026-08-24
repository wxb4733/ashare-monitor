"""外部数据导入（Wind/天眼查 MCP 回填落地接口）单元测试。"""

import pytest


def test_import_klines_json(tmp_path, monkeypatch):
    """K 线 JSON 导入：幂等 + 日期格式归一。"""
    from ashare_monitor import storage
    from ashare_monitor.import_data import import_klines_json

    import sqlite3

    db = str(tmp_path / "imp.db")

    def _mk(db_path=storage.DB_PATH):
        conn = sqlite3.connect(db)
        conn.executescript(storage._SCHEMA)
        return conn

    # get_conn = _connect 包装 → patch _connect 一处即生效
    monkeypatch.setattr(storage, "_connect", _mk)

    data = [
        {"date": "2026-08-21", "open": 90.35, "close": 90.47,
         "high": 91.08, "low": 89.72, "volume": 17886205},
        {"date": "20260824", "open": 90.01, "close": 90.66,   # yyyyMMdd 格式
         "high": 91.49, "low": 89.40, "volume": 27364741},
    ]
    n1 = import_klines_json(data, "ashare", "002594", db_path=db)
    assert n1 == 2
    n2 = import_klines_json(data, "ashare", "002594", db_path=db)
    assert n2 == 0                       # 幂等
    rows = storage.load_klines("002594", "ashare")
    assert len(rows) == 2
    assert rows[-1]["date"] == "2026-08-24"
    assert rows[-1]["close"] == pytest.approx(90.66)


def test_import_company_profile_roundtrip(tmp_path, monkeypatch):
    """企业画像导入/读取/全量。"""
    from ashare_monitor import storage
    from ashare_monitor.import_data import (
        get_all_company_profiles,
        import_company_profile,
        load_company_profile,
    )

    db = str(tmp_path / "cp.db")
    orig = storage.get_conn
    monkeypatch.setattr(storage, "get_conn",
                        lambda db_path=storage.DB_PATH: orig(db_path=db))

    profile = {"法定代表人": "王传福", "注册资本": "911719.7565万人民币",
               "成立日期": "1995-02-10", "规模": "大型",
               "标签": ["A股(正常上市)", "制造业单项冠军企业"]}
    assert import_company_profile("比亚迪股份有限公司", profile, db_path=db)
    p = load_company_profile("比亚迪股份有限公司", db_path=db)
    assert p["法定代表人"] == "王传福"
    assert p["标签"] == ["A股(正常上市)", "制造业单项冠军企业"]
    assert get_all_company_profiles(db_path=db)["比亚迪股份有限公司"][
        "规模"] == "大型"
    assert load_company_profile("不存在公司", db_path=db) is None


def test_check_company_profile_dim(monkeypatch):
    """check 工商画像维度：有导入才显示。"""
    from ashare_monitor.check import check_stock

    profiles = {
        "比亚迪股份有限公司": {"规模": "大型", "成立日期": "1995-02-10",
                          "标签": ["A股(正常上市)", "港股(正常上市)"]},
        "贵州茅台酒股份有限公司": {"规模": "大型", "标签": []},
    }
    monkeypatch.setattr("ashare_monitor.import_data.get_all_company_profiles",
                        lambda db_path=None: profiles)
    checks = check_stock("002594", "比亚迪", "ashare")
    names = {c.name for c in checks}
    assert "工商画像" in names
    item = next(c for c in checks if c.name == "工商画像")
    assert item.status == "OK"
    assert "大型" in str(item.detail)
    assert "1995-02-10" in str(item.detail)
