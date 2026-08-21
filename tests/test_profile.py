"""公司档案单元测试（mock 数据源）。"""

import pytest

from ashare_monitor.profile import (
    CompanyProfile,
    build_profile_report,
    fetch_profile,
    infer_controller,
)


def test_fetch_profile(monkeypatch):
    class _R:
        def get(self, k, default=None):
            return _DATA.get(k, default)

        def __getitem__(self, k):
            return _DATA.get(k)

    _DATA = {
        "A股简称": "比亚迪", "公司名称": "比亚迪股份有限公司",
        "英文名称": "BYD Company Limited", "法人代表": "王传福",
        "注册资金": "911719.7565", "成立日期": "2002-06-11 00:00:00",
        "上市日期": "2011-06-30 00:00:00", "所属行业": "汽车制造业",
        "所属市场": "深交所主板", "注册地址": "广东省深圳市大鹏新区",
        "办公地址": "广东省深圳市坪山区", "官方网站": "www.bydglobal.com",
        "联系电话": "0755-89888888", "电子邮箱": "db@byd.com",
        "主营业务": "二次充电电池业务", "经营范围": "锂离子电池",
        "H股代码": "01211",
    }

    class _DF:
        empty = False

        @property
        def iloc(self):
            return [_R()]

    monkeypatch.setattr("akshare.stock_profile_cninfo",
                        lambda symbol: _DF())
    p = fetch_profile("002594", "ashare")
    assert p.name == "比亚迪"
    assert p.legal_person == "王传福"
    assert p.reg_capital == pytest.approx(911719.7565)
    assert p.founded == "2002-06-11"
    assert p.listed == "2011-06-30"
    assert p.hk_code == "01211"
    assert not p.errors


def test_fetch_profile_hk_unsupported():
    p = fetch_profile("01211", "hk")
    assert p.errors  # 港股如实标注


def test_fetch_profile_error(monkeypatch):
    monkeypatch.setattr("akshare.stock_profile_cninfo",
                        lambda symbol: (_ for _ in ()).throw(RuntimeError("x")))
    p = fetch_profile("002594", "ashare")
    assert p.errors


def test_infer_controller():
    from ashare_monitor.holders import TopHolder

    holders = [
        TopHolder(1, "HKSCC NOMINEES LIMITED", "流通H股", 3681473217, 40.38,
                  "增持", 0.2),
        TopHolder(2, "王传福", "流通A股", 1540871550, 16.9, "不变", None),
        TopHolder(3, "吕向阳", "流通A股", 717685860, 7.87, "不变", None),
        TopHolder(4, "融捷投资控股集团有限公司", "流通A股", 465448806, 5.11,
                  "不变", None),
    ]
    assert infer_controller(holders) == "王传福(16.90%)"


def test_build_profile_report():
    from ashare_monitor.holders import TopHolder

    p = CompanyProfile(
        code="002594", market="ashare", name="比亚迪",
        full_name="比亚迪股份有限公司", legal_person="王传福",
        reg_capital=911719.7565, founded="2002-06-11", listed="2011-06-30",
        industry="汽车制造业", market_board="深交所主板",
        reg_address="广东省深圳市大鹏新区", main_biz="二次充电电池业务",
    )
    holders = [
        TopHolder(1, "HKSCC NOMINEES LIMITED", "流通H股", 3681473217, 40.38,
                  "增持", 0.2),
        TopHolder(2, "王传福", "流通A股", 1540871550, 16.9, "不变", None),
    ]
    html, md = build_profile_report(p, holders, "2026-03-31",
                                    as_of="2026-08-21")
    assert "公司档案" in html
    assert "王传福" in html and "91.17 亿元" in html
    assert "40.38%" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 公司档案 比亚迪")
