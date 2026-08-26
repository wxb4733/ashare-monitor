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
    """check 工商画像维度：有导入才显示（含来源/新鲜度）。"""
    from ashare_monitor.check import check_stock

    profiles = {
        "比亚迪股份有限公司": {"规模": "大型", "成立日期": "1995-02-10",
                          "标签": ["A股(正常上市)", "港股(正常上市)"]},
        "贵州茅台酒股份有限公司": {"规模": "大型", "标签": []},
    }
    meta = {"比亚迪股份有限公司": {"updated": "2026-08-25", "source": "天眼查"}}
    monkeypatch.setattr("ashare_monitor.import_data.get_all_company_profiles",
                        lambda db_path=None: profiles)
    monkeypatch.setattr("ashare_monitor.import_data.get_profile_meta",
                        lambda db_path=None: meta)
    checks = check_stock("002594", "比亚迪", "ashare")
    names = {c.name for c in checks}
    assert "工商画像" in names
    item = next(c for c in checks if c.name == "工商画像")
    assert item.status == "OK"
    assert "大型" in str(item.detail)
    assert "1995-02-10" in str(item.detail)
    assert "来源 天眼查" in str(item.detail)


def test_import_ip_assets(tmp_path, monkeypatch):
    """知识产权导入：专利/论文合并去重。"""
    from ashare_monitor import storage
    from ashare_monitor.import_data import (
        get_all_ip_assets,
        import_ip_assets,
        load_ip_assets,
    )

    db = str(tmp_path / "ip.db")

    def _mk(db_path=storage.DB_PATH):
        import sqlite3

        conn = sqlite3.connect(db)
        conn.executescript(storage._SCHEMA)
        return conn

    monkeypatch.setattr(storage, "_connect", _mk)

    p1 = [{"pn": "CN122619700A", "title": "一种负极片", "date": "2026-08-21"}]
    a1 = [{"title": "Dynamic Pricing", "date": "2026-01-23"}]
    assert import_ip_assets("比亚迪股份有限公司", patents=p1, papers=a1,
                            db_path=db)
    # 重复导入不重复（upsert 合并去重）
    p2 = [{"pn": "CN122619700A", "title": "一种负极片", "date": "2026-08-21"},
          {"pn": "CN122607746A", "title": "翻转控制方法", "date": "2026-08-21"}]
    import_ip_assets("比亚迪股份有限公司", patents=p2, papers=a1, db_path=db)
    ip = load_ip_assets("比亚迪股份有限公司", db_path=db)
    assert len(ip["patents"]) == 2        # 去重后 2 件
    assert len(ip["papers"]) == 1
    assert get_all_ip_assets(db_path=db)["比亚迪股份有限公司"]["patents"][0][
        "pn"] == "CN122619700A"
    assert load_ip_assets("不存在公司", db_path=db) is None


def test_check_ip_dim(monkeypatch):
    """check 知识产权维度（含质量/来源/新鲜度）。"""
    from ashare_monitor.check import check_stock

    ips = {"比亚迪股份有限公司": {
        "patents": [{"pn": "CN122619700A", "title": "一种负极片",
                     "date": "2026-08-21", "legal_status": "active",
                     "ipc": "H01M4/36"},
                    {"pn": "CN122607746A", "title": "翻转控制方法",
                     "date": "2026-06-01", "legal_status": "pending",
                     "ipc": "B60T7/12"}],
        "papers": [{"title": "Dynamic Pricing", "date": "2026-01-23"}],
        "updated": "2026-08-25"}}
    ip_meta = {"比亚迪股份有限公司": {"updated": "2026-08-25", "source": "智慧芽"}}
    monkeypatch.setattr("ashare_monitor.import_data.get_all_ip_assets",
                        lambda db_path=None: ips)
    monkeypatch.setattr("ashare_monitor.import_data.get_ip_meta",
                        lambda db_path=None: ip_meta)
    checks = check_stock("002594", "比亚迪", "ashare")
    item = next(c for c in checks if c.name == "知识产权")
    assert item.status == "OK"
    d = str(item.detail)
    assert "专利 2 件" in d
    assert "论文 1 篇" in d
    assert "有效 1/申请中 1" in d      # 专利质量
    assert "技术 H01M 为主" in d       # IPC 聚焦
    assert "近3年 2 件" in d
    assert "来源 智慧芽" in d          # 数据血缘
    assert "30 天内更新" in d          # 新鲜度


def test_check_ip_dim_code_fallback(monkeypatch, tmp_path):
    """check 知识产权/工商画像：非自选股（name=纯代码）经队列兜底匹配。"""
    from ashare_monitor.check import check_stock

    ips = {"宇通客车股份有限公司": {
        "patents": [{"pn": "CN1", "title": "t", "date": "2026-08-01",
                     "legal_status": "active", "ipc": "B60K1/00"}],
        "papers": [], "updated": "2026-08-25"}}
    profs = {"宇通客车股份有限公司": {"规模": "大型"}}
    ip_meta = {"宇通客车股份有限公司": {"updated": "2026-08-25", "source": "智慧芽"}}
    # 队列产物：code→name 映射
    q = tmp_path / "output" / "backfill_queue.json"
    q.parent.mkdir(parents=True)
    q.write_text('[{"code": "600066", "name": "宇通客车"}]', encoding="utf-8")
    monkeypatch.setattr("ashare_monitor.import_data.get_all_ip_assets",
                        lambda db_path=None: ips)
    monkeypatch.setattr("ashare_monitor.import_data.get_ip_meta",
                        lambda db_path=None: ip_meta)
    monkeypatch.setattr("ashare_monitor.import_data.get_all_company_profiles",
                        lambda db_path=None: profs)
    monkeypatch.setattr(
        "ashare_monitor.check._lookup_name_by_code",
        lambda code: "宇通客车" if code == "600066" else None)
    checks = check_stock("600066", "600066", "ashare")  # name 退化为代码
    names = {c.name for c in checks}
    assert "工商画像" in names
    assert "知识产权" in names
    ip = next(c for c in checks if c.name == "知识产权")
    assert "专利 1 件" in str(ip.detail)


def test_profile_ip_meta(tmp_path, monkeypatch):
    """get_profile_meta / get_ip_meta：返回 updated + source。"""
    from ashare_monitor import storage
    from ashare_monitor.import_data import (
        get_ip_meta,
        get_profile_meta,
        import_company_profile,
        import_ip_assets,
    )

    db = str(tmp_path / "meta.db")
    orig = storage.get_conn
    monkeypatch.setattr(storage, "get_conn",
                        lambda db_path=storage.DB_PATH: orig(db_path=db))

    import_company_profile("测试公司", {"规模": "大型"}, db_path=db)
    import_ip_assets("测试公司", patents=[{"pn": "CN1", "title": "t"}],
                     db_path=db)
    pm = get_profile_meta(db_path=db)
    im = get_ip_meta(db_path=db)
    assert pm["测试公司"]["source"] == "天眼查"
    assert pm["测试公司"]["updated"]  # 非空
    assert im["测试公司"]["source"] == "智慧芽"
    assert im["测试公司"]["updated"]
