"""诉讼监控单元测试（mock akshare）。"""

import pytest

from ashare_monitor.litigation import (
    Lawsuit,
    build_litigation_report,
    load_saved_lawsuits,
    save_lawsuits,
    scan_watchlist_lawsuits,
)


def _fake_df():
    import pandas as pd

    return pd.DataFrame([
        {"证券代码": "002594", "证券简称": "比亚迪",
         "公告统计区间": "2026-01-01---2026-08-20", "诉讼次数": 3,
         "诉讼金额": 2500.0},
        {"证券代码": "000001", "证券简称": "平安银行",
         "公告统计区间": "2026-01-01---2026-08-20", "诉讼次数": 1,
         "诉讼金额": 195400.0},
    ])


def test_scan_watchlist(monkeypatch):
    monkeypatch.setattr("akshare.stock_cg_lawsuit_cninfo",
                        lambda *a, **k: _fake_df())

    class _Cfg:
        watchlist = [
            {"code": "002594", "market": "ashare", "name": "比亚迪"},
            {"code": "01211", "market": "hk", "name": "比亚迪股份"},
        ]

    rows = scan_watchlist_lawsuits(_Cfg(), days=365)
    assert len(rows) == 1
    assert rows[0].code == "002594"
    assert rows[0].name == "比亚迪"
    assert rows[0].count == 3
    assert rows[0].amount == pytest.approx(2500.0)


def test_save_and_load(tmp_path, monkeypatch):
    import ashare_monitor.storage as storage

    db = str(tmp_path / "lit.db")
    orig_conn = storage.get_conn
    monkeypatch.setattr("ashare_monitor.storage.get_conn",
                        lambda: orig_conn(db_path=db))
    rows = [
        Lawsuit("002594", "比亚迪", "2026-01---2026-08", 3, 2500.0,
                "2026-08-21 12:00:00"),
    ]
    added = save_lawsuits(rows)
    assert added == 1
    # 重复入库不新增
    assert save_lawsuits(rows) == 0
    saved = load_saved_lawsuits("002594")
    assert len(saved) == 1
    assert saved[0].count == 3


def test_build_litigation_report():
    rows = [
        Lawsuit("002594", "比亚迪", "2026-01-01---2026-08-20", 3, 2500.0,
                "2026-08-21 12:00:00"),
        Lawsuit("000001", "平安银行", "2026-01-01---2026-08-20", 1,
                195400.0, "2026-08-21 12:00:00"),
    ]
    html, md = build_litigation_report(rows, 365, as_of="2026-08-21")
    assert "诉讼监控" in html
    assert "比亚迪" in html and "2500 万" in html
    assert "19.54 亿" in html  # 195400 万 → 1.95 亿？ 见断言修正
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 诉讼监控")
