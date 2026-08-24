"""a-stock-data 融合模块单元测试。"""

import pytest


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def json(self):
        return {}


def test_tencent_quote_rich_parse(monkeypatch):
    from ashare_monitor.a_stock_data import tencent_quote_rich

    # 腾讯字段（稀疏填充）：1 名称 / 3 现价 / 32 涨跌% / 38 换手 /
    # 39 PE / 44 总市值(亿) / 46 PB
    parts = [""] * 53
    parts[1], parts[3], parts[4], parts[5] = "贵州茅台", "1304.66", "1272.83", "1295.00"
    parts[32], parts[38] = "2.50", "0.39"
    parts[39], parts[44], parts[46] = "20.04", "16309", "6.49"
    line = 'v_sh600519="' + "~".join(parts) + '";'
    monkeypatch.setattr("ashare_monitor.a_stock_data.requests.get",
                        lambda *a, **k: _FakeResp(line))
    q = tencent_quote_rich(["600519"])
    assert "600519" in q
    v = q["600519"]
    assert v["name"] == "贵州茅台"
    assert v["price"] == pytest.approx(1304.66)
    assert v["pe_ttm"] == pytest.approx(20.04)
    assert v["pb"] == pytest.approx(6.49)
    assert v["mcap_yi"] == pytest.approx(16309)


def test_ths_hot_reason(monkeypatch):
    from ashare_monitor.a_stock_data import ths_hot_reason

    class _R:
        def json(self):
            return {"errocode": 0, "data": [
                {"code": "600519", "name": "贵州茅台", "reason": "白酒+AI算力",
                 "zhangfu": "9.99", "close": "1300.0", "huanshou": "1.2",
                 "chengjiaoe": "5e9"},
                {"code": "002594", "name": "比亚迪", "reason": "新能源车出海",
                 "zhangfu": "5.5", "close": "90.0", "huanshou": "0.8",
                 "chengjiaoe": "3e9"},
            ]}

    monkeypatch.setattr("ashare_monitor.a_stock_data.requests.get",
                        lambda *a, **k: _R())
    hot = ths_hot_reason("2026-08-24")
    assert len(hot) == 2
    assert hot[0]["code"] == "600519"       # 按涨幅降序
    assert hot[0]["reason"] == "白酒+AI算力"


def test_dragon_tiger_board(monkeypatch):
    from ashare_monitor import a_stock_data as ad

    calls = {"n": 0}

    def fake_dc(report_name, columns="ALL", filter_str="", page_size=50,
                sort_columns="", sort_types="-1"):
        calls["n"] += 1
        if report_name == "RPT_DAILYBILLBOARD_DETAILSNEW":
            return [{"TRADE_DATE": "2026-08-21",
                     "EXPLANATION": "日涨幅偏离值达7%",
                     "BILLBOARD_NET_AMT": 5.0e7, "TURNOVERRATE": 8.5}]
        if "BUY" in report_name:
            return [{"OPERATEDEPT_NAME": "机构专用", "OPERATEDEPT_CODE": "0",
                     "BUY": 1.0e7, "SELL": 0, "NET": 1.0e7}]
        return [{"OPERATEDEPT_NAME": "散户席位", "OPERATEDEPT_CODE": "1",
                 "BUY": 0, "SELL": 2.0e7, "NET": -2.0e7}]

    monkeypatch.setattr("ashare_monitor.a_stock_data.eastmoney_datacenter",
                        fake_dc)
    data = ad.dragon_tiger_board("002594", "2026-08-24")
    assert len(data["records"]) == 1
    assert data["records"][0]["net_buy_wan"] == pytest.approx(5000.0)
    assert data["institution"]["buy_wan"] == pytest.approx(1000.0)
    assert data["institution"]["net_wan"] == pytest.approx(1000.0)


def test_margin_trading(monkeypatch):
    from ashare_monitor import a_stock_data as ad

    monkeypatch.setattr(
        "ashare_monitor.a_stock_data.eastmoney_datacenter",
        lambda *a, **k: [{"DATE": "2026-08-21", "RZYE": 2.0e10,
                          "RZMRE": 5.0e9, "RQYE": 1.0e8,
                          "RZRQYE": 2.01e10}])
    rows = ad.margin_trading("600519")
    assert rows[0]["date"] == "2026-08-21"
    assert rows[0]["rzye"] == pytest.approx(2.0e10)


def test_block_trade(monkeypatch):
    from ashare_monitor import a_stock_data as ad

    monkeypatch.setattr(
        "ashare_monitor.a_stock_data.eastmoney_datacenter",
        lambda *a, **k: [{"TRADE_DATE": "2026-08-21", "DEAL_PRICE": 1200.0,
                          "CLOSE_PRICE": 1300.0, "DEAL_VOLUME": 1000,
                          "DEAL_AMT": 1.2e6, "BUYER_NAME": "机构专用",
                          "SELLER_NAME": "某某营业部"}])
    rows = ad.block_trade("600519")
    assert rows[0]["premium_pct"] == pytest.approx(-7.69, abs=0.01)  # 折价
    assert rows[0]["buyer"] == "机构专用"


def test_fund_flow_120d(monkeypatch):
    from ashare_monitor import a_stock_data as ad

    class _R:
        def json(self):
            return {"data": {"klines": [
                "2026-08-21,1.0e7,2.0e6,3.0e6,4.0e6,5.0e6,0,0",
                "2026-08-20,-5.0e6,-1.0e6,-1.0e6,-2.0e6,-3.0e6,0,0",
            ]}}

    monkeypatch.setattr("ashare_monitor.a_stock_data.em_get",
                        lambda *a, **k: _R())
    rows = ad.stock_fund_flow_120d("600519")
    assert len(rows) == 2
    assert rows[0]["main_net"] == pytest.approx(1.0e7)
    assert rows[0]["super_net"] == pytest.approx(5.0e6)


def test_sina_financial_report(monkeypatch):
    from ashare_monitor.a_stock_data import sina_financial_report

    class _R:
        def json(self):
            return {"result": {"data": {"report_list": {
                "20260331": {"data": [
                    {"item_title": "营业收入", "item_value": "9.07e10",
                     "item_tongbi": "0.05"},
                    {"item_title": "净利润", "item_value": "4.6e10",
                     "item_tongbi": ""},
                ]},
                "20251231": {"data": [
                    {"item_title": "营业收入", "item_value": "8.5e10",
                     "item_tongbi": ""},
                ]},
            }}}}

    monkeypatch.setattr("ashare_monitor.a_stock_data.requests.get",
                        lambda *a, **k: _R())
    rows = sina_financial_report("600519", "lrb", num=2)
    assert len(rows) == 2
    assert rows[0]["报告期"] == "2026-03-31"
    assert rows[0]["营业收入"] == "9.07e10"
    assert rows[0]["营业收入_同比"] == "0.05"     # 有同比附 _同比 键
    assert "净利润_同比" not in rows[0]            # 无同比不加键


def test_cninfo_announcements(monkeypatch):
    from ashare_monitor.a_stock_data import cninfo_announcements

    class _R:
        def json(self):
            return {"announcements": [
                {"announcementTitle": "2026年半年度报告",
                 "announcementTypeName": "定期报告",
                 "announcementTime": 1787308800000,
                 "announcementId": "12345"},
            ]}

    monkeypatch.setattr("ashare_monitor.a_stock_data.requests.post",
                        lambda *a, **k: _R())
    anns = cninfo_announcements("600519")
    assert len(anns) == 1
    assert anns[0]["title"] == "2026年半年度报告"
    assert "2026-" in anns[0]["date"]             # 时间戳转日期
    assert "annoId=12345" in anns[0]["url"]


def test_eastmoney_reports(monkeypatch):
    from ashare_monitor.a_stock_data import eastmoney_reports

    class _R:
        def json(self):
            return {"data": [
                {"publishDate": "2026-08-21 09:00",
                 "orgSName": "西南证券", "emRatingName": "买入",
                 "title": "2026年中报点评", "infoCode": "ABC123"},
                {"publishDate": "2026-08-19 09:00",
                 "orgSName": "万联证券", "emRatingName": "增持",
                 "title": "提价与直销双轮驱动", "infoCode": "DEF456"},
            ], "TotalPage": 1}

    monkeypatch.setattr("ashare_monitor.a_stock_data.em_get",
                        lambda *a, **k: _R())
    reps = eastmoney_reports("600519", max_pages=1)
    assert len(reps) == 2
    assert reps[0]["orgSName"] == "西南证券"
    assert reps[0]["infoCode"] == "ABC123"


def test_download_pdf(tmp_path, monkeypatch):
    from ashare_monitor.a_stock_data import download_pdf

    class _R:
        status_code = 200
        content = b"%PDF-1.4 " + b"x" * 2048

    monkeypatch.setattr("ashare_monitor.a_stock_data.em_get",
                        lambda *a, **k: _R())
    path = download_pdf({"infoCode": "ABC123",
                         "publishDate": "2026-08-21",
                         "orgSName": "西南证券",
                         "title": "中报点评"},
                        target_dir=str(tmp_path))
    assert path is not None
    assert path.endswith(".pdf")
    with open(path, "rb") as f:
        assert f.read().startswith(b"%PDF")


def test_ths_eps_forecast(monkeypatch):
    from ashare_monitor.a_stock_data import ths_eps_forecast

    html = ('<html><table><tr><th>年份</th><th>预测机构数</th><th>均值</th>'
            '<th>最小值</th><th>最大值</th></tr>'
            '<tr><td>2026</td><td>32</td><td>55.2</td><td>48.1</td>'
            '<td>62.3</td></tr></table></html>')

    class _R:
        encoding = "gbk"
        text = html

    monkeypatch.setattr("ashare_monitor.a_stock_data.requests.get",
                        lambda *a, **k: _R())
    rows = ths_eps_forecast("600519")
    assert len(rows) == 1
    assert any("2026" in str(v) for v in rows[0].values())
