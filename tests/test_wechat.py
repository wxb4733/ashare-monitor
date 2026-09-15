"""公众号图文生成与草稿箱推送单元测试。"""

import json
import re

import pytest


class _Resp:
    """极简 requests 响应替身。"""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Radar:
    def __init__(self, total, verdict):
        self.total = total
        self.verdict = verdict


def _data():
    """构造一份 daily.build_daily_data 形态的样例数据。"""
    return {
        "items": [
            {"code": "600519", "name": "贵州茅台", "market": "ashare",
             "quote": {"price": 1304.66, "change_pct": 2.5,
                       "date": "2026-09-15"},
             "radar": _Radar(2.3, "偏多"), "timing": ["站上 20 日线"],
             "events": [], "valuation": "PE 30% / PB 40%",
             "ratings": 3, "corp": []},
            {"code": "300750", "name": "宁德时代", "market": "ashare",
             "quote": {"price": 180.0, "change_pct": -1.2,
                       "date": "2026-09-15"},
             "radar": _Radar(-1.5, "偏空"), "timing": [],
             "events": ["解禁 2026-09-18"], "valuation": None,
             "ratings": 0, "corp": ["减持:2026-09-14"]},
        ],
        "health": ["贵州茅台(600519) K线: 2026-09-15（正常）"],
    }


# ---------------- 渲染 ----------------

def test_article_is_inline_style_only():
    """公众号编辑器会剥离 <style> 与 class，正文必须全行内样式。"""
    from ashare_monitor.wechat import build_wechat_article

    html = build_wechat_article(_data(), as_of="2026-09-15")
    assert "<style" not in html
    assert "class=" not in html
    assert "style=" in html


def test_article_no_duplicate_color_in_style():
    """同一 style 内重复声明 color 会被后者覆盖，属隐患。"""
    from ashare_monitor.wechat import build_wechat_article

    html = build_wechat_article(_data(), as_of="2026-09-15")
    for style in re.findall(r'style="([^"]*)"', html):
        assert style.count("color:") <= 1, style


def test_article_up_red_down_green():
    """A 股习惯：涨红跌绿。"""
    from ashare_monitor.wechat import DOWN, UP, build_wechat_article

    html = build_wechat_article(_data(), as_of="2026-09-15")
    assert f"color:{UP}" in html
    assert f"color:{DOWN}" in html
    assert "+2.50%" in html
    assert "-1.20%" in html


def test_article_contains_names_and_disclaimer():
    from ashare_monitor.wechat import build_wechat_article

    html = build_wechat_article(_data(), as_of="2026-09-15")
    assert "贵州茅台" in html
    assert "宁德时代" in html
    assert "不构成任何投资建议" in html
    assert "2026-09-15" in html


def test_article_handles_empty_items():
    from ashare_monitor.wechat import build_wechat_article

    html = build_wechat_article({"items": [], "health": []},
                                as_of="2026-09-15")
    assert "不构成任何投资建议" in html


def test_article_missing_quote_renders_placeholder():
    """行情缺失不应抛异常，降级为占位符。"""
    from ashare_monitor.wechat import build_wechat_article

    data = {"items": [{"code": "BTCUSDT", "name": "比特币",
                       "market": "crypto", "quote": {}, "radar": None,
                       "timing": [], "events": [], "valuation": None,
                       "ratings": 0, "corp": []}],
            "health": []}
    html = build_wechat_article(data, as_of="2026-09-15")
    assert "比特币" in html
    assert "—" in html


def test_page_wraps_article():
    from ashare_monitor.wechat import build_wechat_article, build_wechat_page

    art = build_wechat_article(_data(), as_of="2026-09-15")
    page = build_wechat_page(art, "自选股监控日报 2026-09-15")
    assert page.startswith("<!DOCTYPE html>")
    assert "<title>自选股监控日报 2026-09-15</title>" in page
    assert art in page


def test_text_version():
    from ashare_monitor.wechat import build_wechat_text

    txt = build_wechat_text(_data(), as_of="2026-09-15")
    assert "自选股监控日报 2026-09-15" in txt
    assert "贵州茅台(600519)" in txt
    assert "择时：站上 20 日线" in txt
    assert "不构成任何投资建议" in txt


def test_digest_within_wechat_limit():
    """公众号 digest 上限 120 字。"""
    from ashare_monitor.wechat import build_wechat_digest

    digest = build_wechat_digest(_data())
    assert len(digest) <= 120
    assert "2 只" in digest


# ---------------- 草稿箱客户端 ----------------

def _patch_token(monkeypatch, payload=None):
    monkeypatch.setattr(
        "requests.get",
        lambda *a, **k: _Resp(payload
                              or {"access_token": "TK", "expires_in": 7200}))


def test_client_requires_credentials():
    from ashare_monitor.wechat import WeChatDraftClient

    with pytest.raises(ValueError):
        WeChatDraftClient("", "")
    with pytest.raises(ValueError):
        WeChatDraftClient("app", "  ")


def test_token_is_cached(monkeypatch):
    from ashare_monitor.wechat import WeChatDraftClient

    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        return _Resp({"access_token": "TK", "expires_in": 7200})

    monkeypatch.setattr("requests.get", fake_get)
    client = WeChatDraftClient("app", "sec")
    assert client.get_token() == "TK"
    assert client.get_token() == "TK"
    assert calls["n"] == 1


def test_token_error_raises(monkeypatch):
    from ashare_monitor.wechat import WeChatDraftClient

    _patch_token(monkeypatch, {"errcode": 40164, "errmsg": "invalid ip"})
    with pytest.raises(RuntimeError, match="access_token"):
        WeChatDraftClient("app", "sec").get_token()


def test_add_draft_payload(monkeypatch):
    from ashare_monitor.wechat import WeChatDraftClient

    captured = {}

    def fake_post(url, params=None, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["body"] = json.loads(data.decode("utf-8"))
        return _Resp({"media_id": "MID"})

    _patch_token(monkeypatch)
    monkeypatch.setattr("requests.post", fake_post)

    media_id = WeChatDraftClient("app", "sec").add_draft(
        "标题", "<p>正文</p>", author="我", digest="摘要")

    assert media_id == "MID"
    assert captured["url"].endswith("/draft/add")
    art = captured["body"]["articles"][0]
    assert art["title"] == "标题"
    assert art["content"] == "<p>正文</p>"
    assert art["author"] == "我"
    assert art["digest"] == "摘要"


def test_add_draft_error_raises(monkeypatch):
    """个人订阅号调用发布类接口会返回 48001，错误信息需带权限提示。"""
    from ashare_monitor.wechat import WeChatDraftClient

    _patch_token(monkeypatch)
    monkeypatch.setattr(
        "requests.post",
        lambda *a, **k: _Resp({"errcode": 48001, "errmsg": "api unauthorized"}))

    with pytest.raises(RuntimeError, match="48001"):
        WeChatDraftClient("app", "sec").add_draft("t", "<p>x</p>")


# ---------------- 配置 ----------------

def test_config_wechat_section(tmp_path, monkeypatch):
    from ashare_monitor.config import load_config

    monkeypatch.delenv("WECHAT_APPID", raising=False)
    monkeypatch.delenv("WECHAT_SECRET", raising=False)

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "watchlist: []\n"
        "wechat:\n"
        '  appid: "wx123"\n'
        '  secret: "s3cr3t"\n'
        '  author: "小明"\n'
        '  title_prefix: "监控日报 "\n',
        encoding="utf-8")

    cfg = load_config(str(cfg_file))
    assert cfg.wechat.appid == "wx123"
    assert cfg.wechat.secret == "s3cr3t"
    assert cfg.wechat.author == "小明"
    assert cfg.wechat.title_prefix == "监控日报 "


def test_config_wechat_env_overrides(tmp_path, monkeypatch):
    """环境变量优先，便于定时任务注入凭据而不落盘。"""
    from ashare_monitor.config import load_config

    monkeypatch.setenv("WECHAT_APPID", "env_app")
    monkeypatch.setenv("WECHAT_SECRET", "env_sec")

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "watchlist: []\n"
        "wechat:\n"
        '  appid: "file_app"\n'
        '  secret: "file_sec"\n',
        encoding="utf-8")

    cfg = load_config(str(cfg_file))
    assert cfg.wechat.appid == "env_app"
    assert cfg.wechat.secret == "env_sec"


def test_config_wechat_defaults(tmp_path, monkeypatch):
    """未配置 wechat 段时应有安全默认值。"""
    from ashare_monitor.config import load_config

    monkeypatch.delenv("WECHAT_APPID", raising=False)
    monkeypatch.delenv("WECHAT_SECRET", raising=False)

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("watchlist: []\n", encoding="utf-8")
    cfg = load_config(str(cfg_file))
    assert cfg.wechat.appid == ""
    assert cfg.wechat.title_prefix == "自选股监控日报 "
