"""A 股市场扫描选股器单元测试（高股息率）。"""

import pytest

from ashare_monitor.screen import ScreenHit, build_screen_report, fetch_dividend_top


def _mock_payload():
    return {"data": {"diff": [
        {"f12": "600900", "f14": "长江电力", "f2": 28.5, "f9": 18.2,
         "f23": 3.1, "f133": 3.85, "f20": 6.97e11},
        {"f12": "601088", "f14": "中国神华", "f2": 38.9, "f9": 12.5,
         "f23": 1.8, "f133": 5.21, "f20": 7.73e11},
        {"f12": "000001", "f14": "ST平安", "f2": 10.5, "f9": 5.0,
         "f23": 0.6, "f133": 4.5, "f20": 2.0e11},
        {"f12": "600519", "f14": "贵州茅台", "f2": 1450.0, "f9": 22.0,
         "f23": 7.0, "f133": 2.1, "f20": 1.8e12},  # 股息率不足 3 被过滤
    ]}}


def test_fetch_dividend_top(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return _mock_payload()

    monkeypatch.setattr("requests.get",
                        lambda *a, **k: _Resp())
    hits = fetch_dividend_top(top_n=10, min_yield=3.0, exclude_st=True)
    # 神华 5.21 > 平安(ST 剔除) > 长电 3.85；茅台 2.1 被过滤
    assert len(hits) == 2
    assert hits[0].name == "中国神华"
    assert hits[0].dividend_yield == pytest.approx(5.21)
    assert hits[1].name == "长江电力"
    assert all("ST" not in h.name.upper() for h in hits)


def test_fetch_dividend_mv_filter(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return _mock_payload()

    monkeypatch.setattr("requests.get",
                        lambda *a, **k: _Resp())
    hits = fetch_dividend_top(top_n=10, min_yield=3.0, exclude_st=True,
                              min_mv=500)  # 500 亿以上
    assert len(hits) == 2  # 神华/长电均 > 500 亿
    hits2 = fetch_dividend_top(top_n=10, min_yield=3.0, exclude_st=True,
                               max_mv=500)
    assert len(hits2) == 0  # 无 < 500 亿的高股息（ST 已剔除）


def test_screen_raises_when_source_down(monkeypatch):
    monkeypatch.setattr("requests.get",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("connect fail")))
    monkeypatch.setattr("akshare.stock_zh_a_spot_em",
                        lambda: (_ for _ in ()).throw(
                            RuntimeError("akshare fail")))
    from ashare_monitor.screen import screen_dividend

    with pytest.raises(RuntimeError):
        screen_dividend()


def test_build_screen_report():
    hits = [
        ScreenHit("601088", "中国神华", 38.9, 5.21, 12.5, 1.8, 7.73e11),
        ScreenHit("600900", "长江电力", 28.5, 3.85, 18.2, 3.1, 6.97e11),
    ]
    html, md = build_screen_report(hits, "高股息率",
                                   {"top": 60, "min_yield%": 3.0},
                                   as_of="2026-08-22")
    assert "高股息率选股" in html
    assert "中国神华" in html and "5.21" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 高股息率选股")
