"""官网档案与公告监控单元测试。"""

import pytest

from ashare_monitor.site import (
    SiteLinks,
    SiteNotice,
    build_site_report,
    fetch_site_notices,
    site_links,
)


def test_site_links_config_override(monkeypatch):
    cfg = type("C", (), {"sites": {
        "002594": {"website": "https://www.byd.com/",
                   "notice_url": "https://www.byd.com/ir/announcements/"},
    }})()
    sl = site_links(cfg, "002594", "比亚迪")
    assert sl.website == "https://www.byd.com/"
    assert sl.notice_url == "https://www.byd.com/ir/announcements/"
    assert "config" in sl.sources


def test_site_links_from_profile(monkeypatch):
    cfg = type("C", (), {"sites": {}})()

    class P:
        website = "https://www.bydglobal.com/"

    monkeypatch.setattr("ashare_monitor.profile.fetch_profile",
                        lambda code, market: P())
    sl = site_links(cfg, "002594", "比亚迪")
    assert sl.website == "https://www.bydglobal.com/"
    assert "工商档案" in sl.sources


def test_fetch_site_notices(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        @property
        def text(self):
            return (
                '<html><body>'
                '<a href="/ir/n20260820.html">关于召开2026年第二次临时股东大会的通知</a>'
                '<a href="/news.html">产品新闻页</a>'
                '<a href="javascript:void(0)">返回</a>'
                '</body></html>'
            )

    monkeypatch.setattr("ashare_monitor.site.requests.get",
                        lambda *a, **k: _Resp())
    sl = SiteLinks(code="002594", name="比亚迪",
                   notice_url="https://www.byd.com/ir/")
    notices, status = fetch_site_notices(sl)
    assert status == "ok"
    assert len(notices) == 2  # 公告+新闻
    assert "临时股东大会的通知" in notices[0].title
    assert "n20260820" in notices[0].url


def test_fetch_site_notices_no_url():
    sl = SiteLinks(code="002594", name="比亚迪")
    notices, status = fetch_site_notices(sl)
    assert notices == [] and "未配置" in status


def test_build_site_report():
    links = [SiteLinks("002594", "比亚迪", website="https://www.bydglobal.com/",
                       notice_url="https://www.byd.com/ir/")]
    notices = [SiteNotice("002594", "比亚迪", "临时股东大会通知",
                          "https://www.byd.com/ir/n1.html", "2026-08-20")]
    html, md = build_site_report(links, notices, as_of="2026-08-21")
    assert "官方网站链接与公告监控" in html
    assert "www.bydglobal.com" in html and "临时股东大会通知" in html
    assert "不构成投资建议" in html
    assert md.startswith("---\ntitle: 官网档案与公告")
