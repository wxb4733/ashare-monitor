"""公众号图文生成与草稿箱推送。

把每日监控数据渲染成「微信公众号」可直接粘贴的图文，并可选推入草稿箱。

权限边界（重要）
----------------
自 2025-07 起，微信官方回收了**个人主体账号**与**未认证企业账号**的
``freepublish``（提交发布）接口权限。个人订阅号仍可用：

* ``cgi-bin/token``          获取 access_token
* ``cgi-bin/material/add_material``  上传永久图片素材
* ``cgi-bin/draft/add``      新建草稿

因此本模块的定位是「生成图文 + 推到草稿箱」，最后一步**群发**必须人工在
公众平台后台点击（个人订阅号每天 1 次群发额度）。这不是技术限制，是平台规则。

渲染约束
--------
公众号编辑器会剥离 ``<style>`` 标签与 ``class`` 属性，只保留行内样式，
所以正文所有样式一律写成 inline style。页面级 ``<style>`` 仅服务本地预览，
粘贴时会被丢弃，不影响正文。

涨跌配色遵循 A 股习惯：涨红跌绿。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# A 股习惯：涨红跌绿
UP = "#c62828"
DOWN = "#2e7d32"
FLAT = "#8a9099"
INK = "#1f2329"
BODY = "#3d444d"
MUTED = "#8a9099"
LINE = "#e8eaed"
CARD_BG = "#f7f8fa"

DISCLAIMER = ("本文为公开数据聚合整理，仅供研究参考，不构成任何投资建议。"
              "市场有风险，投资需谨慎。")

_MARKET_LABEL = {
    "ashare": "A股",
    "hk": "港股",
    "us": "美股",
    "crypto": "数字货币",
}


def _chg_color(chg: float | None) -> str:
    """涨红跌绿。"""
    if chg is None:
        return FLAT
    if chg > 0:
        return UP
    if chg < 0:
        return DOWN
    return FLAT


def _chg_text(chg: float | None) -> str:
    return "—" if chg is None else f"{chg:+.2f}%"


def _market_label(market: str) -> str:
    return _MARKET_LABEL.get(str(market), str(market))


def _radar_color(verdict: str) -> str:
    return {"偏多": UP, "偏空": DOWN, "中性": "#b7950b"}.get(verdict, MUTED)


def _radar_text(radar) -> tuple[str, str]:
    """返回 (文本, 颜色)。"""
    if not radar:
        return "—", FLAT
    return f"{radar.total:+.1f} {radar.verdict}", _radar_color(radar.verdict)


def build_wechat_article(data: dict, as_of: str | None = None,
                         intro: str = "") -> str:
    """把日报数据渲染成公众号正文 HTML（全行内样式，可直接粘贴）。

    :param data: ``daily.build_daily_data`` 的返回值（items + health）
    :param as_of: 报告日期，缺省取今天
    :param intro: 导语，缺省按标的数自动生成
    :return: 正文 HTML 片段
    """
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    items = data.get("items", []) or []
    health = data.get("health", []) or []

    blocks: list[str] = []

    # ---------- 导语 ----------
    head = intro or f"{as_of} 自选股监控汇总，共 {len(items)} 只标的。"
    blocks.append(
        f'<p style="margin:0 0 20px;font-size:15px;line-height:1.75;'
        f'color:{BODY}">{head}</p>'
    )

    # ---------- 概览表 ----------
    if items:
        th = (f'padding:8px 6px;font-size:12px;font-weight:400;color:{MUTED};'
              f'border-bottom:1px solid {LINE};text-align:left;')
        th_r = th.replace("text-align:left", "text-align:right")
        # 基础单元格样式不含 color，避免右对齐列出现重复 color 声明
        td_base = (f'padding:11px 6px;font-size:14px;'
                   f'border-bottom:1px solid {LINE};vertical-align:top;')
        td = f'{td_base}color:{INK};'
        td_r = f'{td_base}text-align:right;color:{INK};'

        rows = [
            "<tr>"
            f'<th style="{th}">标的</th>'
            f'<th style="{th_r}">现价</th>'
            f'<th style="{th_r}">涨跌</th>'
            f'<th style="{th_r}">雷达</th>'
            "</tr>"
        ]
        for x in items:
            q = x.get("quote") or {}
            price = f"{q['price']:.2f}" if q.get("price") is not None else "—"
            chg = q.get("change_pct")
            rt, rc = _radar_text(x.get("radar"))
            sub = (f'<br><span style="font-size:12px;color:{MUTED}">'
                   f'{x["code"]} · {_market_label(x.get("market", ""))}</span>')
            rows.append(
                "<tr>"
                f'<td style="{td}">{x["name"]}{sub}</td>'
                f'<td style="{td_r}">{price}</td>'
                f'<td style="{td_base}text-align:right;'
                f'color:{_chg_color(chg)};font-weight:500">{_chg_text(chg)}</td>'
                f'<td style="{td_base}text-align:right;color:{rc}">{rt}</td>'
                "</tr>"
            )
        blocks.append(
            f'<table style="width:100%;border-collapse:collapse;margin:0 0 24px;">'
            + "".join(rows) + "</table>"
        )

    # ---------- 重点提示 ----------
    focus = [x for x in items
             if x.get("timing") or x.get("events") or x.get("corp")]
    if focus:
        blocks.append(_section_title("重点提示"))
        for x in focus:
            lines = []
            if x.get("timing"):
                lines.append(f'择时：{"、".join(x["timing"])}')
            if x.get("events"):
                lines.append(f'事件：{"、".join(x["events"])}')
            if x.get("corp"):
                lines.append(f'公告：{"、".join(x["corp"])}')
            if x.get("valuation"):
                lines.append(f'估值：{x["valuation"]}')
            inner = "".join(
                f'<p style="margin:0 0 4px;font-size:13px;line-height:1.7;'
                f'color:{BODY}">{ln}</p>' for ln in lines
            )
            blocks.append(
                f'<section style="margin:0 0 12px;padding:14px 16px;'
                f'background:{CARD_BG};border-radius:8px;">'
                f'<p style="margin:0 0 8px;font-size:15px;font-weight:500;'
                f'color:{INK}">{x["name"]}'
                f'<span style="font-size:12px;font-weight:400;color:{MUTED}">'
                f'&nbsp;{x["code"]}</span></p>{inner}</section>'
            )

    # ---------- 数据健康 ----------
    if health:
        blocks.append(_section_title("数据健康"))
        blocks.append(
            "".join(
                f'<p style="margin:0 0 4px;font-size:12px;line-height:1.7;'
                f'color:{MUTED}">{h}</p>' for h in health
            )
        )

    # ---------- 免责声明 ----------
    blocks.append(
        f'<p style="margin:24px 0 0;padding-top:16px;'
        f'border-top:1px solid {LINE};font-size:12px;line-height:1.7;'
        f'color:{MUTED}">{DISCLAIMER}</p>'
    )

    return "\n".join(blocks)


def _section_title(text: str) -> str:
    """小节标题（左侧色条 + 文字）。"""
    return (
        f'<p style="margin:26px 0 14px;font-size:16px;font-weight:500;'
        f'color:{INK};border-left:3px solid {UP};padding-left:10px;'
        f'line-height:1.4;">{text}</p>'
    )


def build_wechat_page(article: str, title: str) -> str:
    """包一层完整 HTML 页面，便于浏览器预览与全选复制。

    页面级 ``<style>`` 只服务预览，粘贴进公众号编辑器时会被自动剥离。
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ margin: 0; background: #eceef1; }}
  .preview {{ max-width: 677px; margin: 24px auto; padding: 24px 20px;
             background: #fff; }}
  @media (max-width: 720px) {{ .preview {{ margin: 0; }} }}
</style>
</head>
<body>
<div class="preview">
{article}
</div>
</body>
</html>"""


def build_wechat_text(data: dict, as_of: str | None = None) -> str:
    """纯文本版（备用：直接粘贴为无排版正文，或推送到 webhook）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    items = data.get("items", []) or []
    lines = [f"自选股监控日报 {as_of}", ""]
    for x in items:
        q = x.get("quote") or {}
        price = f"{q['price']:.2f}" if q.get("price") is not None else "—"
        rt, _ = _radar_text(x.get("radar"))
        lines.append(f'{x["name"]}({x["code"]}) {price} '
                     f'{_chg_text(q.get("change_pct"))} 雷达{rt}')
        if x.get("timing"):
            lines.append(f'  择时：{"、".join(x["timing"])}')
        if x.get("events"):
            lines.append(f'  事件：{"、".join(x["events"])}')
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


def build_wechat_digest(data: dict, limit: int = 120) -> str:
    """生成草稿摘要（公众号 digest 上限 120 字）。"""
    items = data.get("items", []) or []
    ups = [x for x in items
           if (x.get("quote") or {}).get("change_pct") is not None
           and x["quote"]["change_pct"] > 0]
    downs = [x for x in items
             if (x.get("quote") or {}).get("change_pct") is not None
             and x["quote"]["change_pct"] < 0]
    parts = [f"自选股 {len(items)} 只"]
    if ups:
        parts.append(f'{len(ups)} 涨（{"、".join(x["name"] for x in ups[:3])}）')
    if downs:
        parts.append(f'{len(downs)} 跌（{"、".join(x["name"] for x in downs[:3])}）')
    focus = [x for x in items if x.get("timing") or x.get("events")]
    if focus:
        parts.append(f'{len(focus)} 只有择时/事件提示')
    digest = "，".join(parts) + "。"
    return digest[:limit]


class WeChatDraftClient:
    """公众号草稿箱客户端。

    个人订阅号可用：``token`` / ``material/add_material`` / ``draft/add``。
    个人订阅号**不可用**：``freepublish``（2025-07 起官方回收）。

    使用前需在公众平台「设置与开发 → 基本配置」取得 AppID/AppSecret，
    并把调用方的公网 IP 加入 IP 白名单，否则会报 ``40164 invalid ip``。
    """

    BASE = "https://api.weixin.qq.com/cgi-bin"

    def __init__(self, appid: str, secret: str, timeout: int = 10):
        self.appid = str(appid or "").strip()
        self.secret = str(secret or "").strip()
        if not self.appid or not self.secret:
            raise ValueError("appid / secret 不能为空")
        self.timeout = timeout
        self._token: str | None = None
        self._expire_at: float = 0.0

    # ---------- 基础 ----------
    def get_token(self, force: bool = False) -> str:
        """获取 access_token（带进程内缓存，提前 5 分钟过期）。"""
        if not force and self._token and time.time() < self._expire_at:
            return self._token

        import requests

        resp = requests.get(
            f"{self.BASE}/token",
            params={"grant_type": "client_credential",
                    "appid": self.appid, "secret": self.secret},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if "access_token" not in payload:
            raise RuntimeError(
                f'获取 access_token 失败: {payload.get("errcode")} '
                f'{payload.get("errmsg")}'
            )
        self._token = payload["access_token"]
        ttl = int(payload.get("expires_in", 7200))
        self._expire_at = time.time() + max(ttl - 300, 60)
        return self._token

    def upload_thumb(self, image_path: str) -> str:
        """上传永久图片素材，返回 thumb_media_id（封面用）。"""
        import requests

        token = self.get_token()
        with open(image_path, "rb") as fh:
            resp = requests.post(
                f"{self.BASE}/material/add_material",
                params={"access_token": token, "type": "image"},
                files={"media": fh},
                timeout=max(self.timeout, 30),
            )
        resp.raise_for_status()
        payload = resp.json()
        if "media_id" not in payload:
            raise RuntimeError(
                f'上传素材失败: {payload.get("errcode")} {payload.get("errmsg")}'
            )
        return payload["media_id"]

    # ---------- 草稿 ----------
    def add_draft(self, title: str, content: str, author: str = "",
                  digest: str = "", thumb_media_id: str = "",
                  content_source_url: str = "") -> str:
        """新建草稿，返回 media_id。"""
        import requests

        article = {
            "title": title,
            "author": author,
            "digest": digest,
            "content": content,
            "content_source_url": content_source_url,
            "thumb_media_id": thumb_media_id,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }
        token = self.get_token()
        resp = requests.post(
            f"{self.BASE}/draft/add",
            params={"access_token": token},
            data=json.dumps({"articles": [article]},
                            ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=max(self.timeout, 30),
        )
        resp.raise_for_status()
        payload = resp.json()
        if "media_id" not in payload:
            code = payload.get("errcode")
            hint = ""
            if code in (48001, 40001):
                hint = "（接口权限不足：个人订阅号无 freepublish 权限，草稿箱接口应可用，请检查 IP 白名单与账号类型）"
            raise RuntimeError(
                f'新建草稿失败: {code} {payload.get("errmsg")}{hint}'
            )
        return payload["media_id"]
