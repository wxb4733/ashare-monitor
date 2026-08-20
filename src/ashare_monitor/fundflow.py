"""资金面监控：个股主力资金流 + 沪深港通概要。

数据源：
- 个股资金流：东方财富 push2 fflow（主力/超大单/大单/中单/小单净流入，元→亿）
- 沪深港通：akshare 东财汇总（北向净买入额自 2024-08 起停止披露，仅交易状态与涨跌家数；
  南向（港股通）仍披露成交净买额）

失败降级：个股资金流 push2 不通时尝试 akshare，仍失败则如实提示无数据。

声明：资金流为公开数据统计，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}

# 板块代码：0=深市 1=沪市（A 股 6 位开头：6→沪 1；其余深 0）
def _secid(code: str) -> str:
    return ("1." if code.startswith("6") else "0.") + code


@dataclass
class FundFlow:
    code: str
    name: str
    market: str
    date: str
    main_net: float | None      # 主力净流入（亿）
    xl_net: float | None        # 超大单净流入（亿）
    l_net: float | None         # 大单净流入（亿）
    m_net: float | None         # 中单净流入（亿）
    s_net: float | None         # 小单净流入（亿）
    source: str = "东财push2"

    def to_dict(self) -> dict:
        return {
            "code": self.code, "name": self.name, "market": self.market,
            "date": self.date, "main_net": self.main_net,
            "xl_net": self.xl_net, "l_net": self.l_net,
            "m_net": self.m_net, "s_net": self.s_net, "source": self.source,
        }


def fetch_fundflow(code: str, market: str, name: str = "") -> FundFlow:
    """查询个股当日主力资金流（失败降级 akshare，再失败抛异常）。"""
    if market == "hk":
        return FundFlow(code, name or code, "hk", "", None, None, None, None, None)
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    resp = requests.get(
        url,
        params={
            "lmt": 1, "klt": 101, "secid": _secid(code),
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56",
        },
        headers=_HEADERS, timeout=10,
    )
    resp.raise_for_status()
    klines = (resp.json().get("data") or {}).get("klines") or []
    if not klines:
        raise RuntimeError(f"{code} 资金流数据为空")
    parts = klines[-1].split(",")
    # f51日期 f52主力 f53小单 f54中单 f55大单 f56超大单（元）
    vals = [float(v) / 1e8 if v else None for v in parts[1:]]
    return FundFlow(
        code=code, name=name or code, market=market, date=parts[0][:10],
        main_net=_r2(vals[0]), xl_net=_r2(vals[4]),
        l_net=_r2(vals[3]), m_net=_r2(vals[2]), s_net=_r2(vals[1]),
    )


def _r2(v: float | None) -> float | None:
    return round(v, 2) if v is not None else None


def fetch_fundflow_ak(code: str, name: str = "") -> FundFlow:
    """akshare 兜底：东财个股资金流排名。"""
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(f"akshare 未安装（可选依赖）: {exc}")
    df = ak.stock_individual_fund_flow(stock=code[-6:], market="sh" if code.startswith("6") else "sz")
    if df is None or df.empty:
        raise RuntimeError(f"akshare {code} 资金流为空")
    last = df.iloc[-1]
    return FundFlow(
        code=code, name=name or code, market="ashare",
        date=str(last.get("日期", ""))[:10],
        main_net=_r2(_num(last.get("主力净流入-净额"))),
        xl_net=_r2(_num(last.get("超大单净流入-净额"))),
        l_net=_r2(_num(last.get("大单净流入-净额"))),
        m_net=_r2(_num(last.get("中单净流入-净额"))),
        s_net=_r2(_num(last.get("小单净流入-净额"))),
        source="akshare",
    )


def _num(v) -> float | None:
    try:
        if v is None or v == "" or v == "--":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_hsgt_summary() -> list[dict]:
    """沪深港通概要（akshare 东财汇总）。北向净买额已停披露 → 0。"""
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(f"akshare 未安装（可选依赖）: {exc}")
    df = ak.stock_hsgt_fund_flow_summary_em()
    if df is None or df.empty:
        raise RuntimeError("沪深港通汇总为空")
    rows = []
    for _, r in df.head(4).iterrows():
        rows.append({
            "date": str(r.get("交易日", ""))[:10],
            "type": str(r.get("类型", "")),
            "board": str(r.get("板块", "")),
            "direction": str(r.get("资金方向", "")),
            "net_buy": _num(r.get("成交净买额")),
            "up": int(r.get("上涨数") or 0),
            "down": int(r.get("下跌数") or 0),
            "index_chg": _num(r.get("指数涨跌幅")),
        })
    return rows


# ---------- 报告 ----------

def build_fundflow_report(flows: list[FundFlow], hsgt: list[dict],
                          as_of: str | None = None) -> tuple[str, str]:
    """生成资金面报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _fmt(v, suffix: str = "", nd: int = 2, sign: bool = True) -> str:
        if v is None:
            return "-"
        return f"{v:+.{nd}f}{suffix}" if sign else f"{v:.{nd}f}{suffix}"

    def _cls(v: float | None) -> str:
        if v is None or v == 0:
            return ""
        return "up" if v > 0 else "down"

    tr = []
    md_rows = [
        "| 标的 | 日期 | 主力净流入 | 超大单 | 大单 | 中单 | 小单 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for f in flows:
        tr.append(
            "<tr>"
            f"<td>{f.name}({f.code})</td><td>{f.date}</td>"
            f'<td class="{_cls(f.main_net)}">{_fmt(f.main_net, " 亿")}</td>'
            f'<td class="{_cls(f.xl_net)}">{_fmt(f.xl_net, " 亿")}</td>'
            f'<td class="{_cls(f.l_net)}">{_fmt(f.l_net, " 亿")}</td>'
            f'<td class="{_cls(f.m_net)}">{_fmt(f.m_net, " 亿")}</td>'
            f'<td class="{_cls(f.s_net)}">{_fmt(f.s_net, " 亿")}</td>'
            "</tr>"
        )
        md_rows.append(
            f"| {f.name}({f.code}) | {f.date} | {_fmt(f.main_net, ' 亿')} | "
            f"{_fmt(f.xl_net, ' 亿')} | {_fmt(f.l_net, ' 亿')} | "
            f"{_fmt(f.m_net, ' 亿')} | {_fmt(f.s_net, ' 亿')} |"
        )

    # 沪深港通
    hsgt_tr = []
    hsgt_md = []
    for r in hsgt:
        direction = "北向" if r["direction"] == "北向" else "南向"
        net = r["net_buy"]
        net_cell = (
            f'<span class="{"down" if net and net < 0 else "up"}">{_fmt(net, " 亿")}</span>'
            if net is not None else "（已停披露）"
        )
        hsgt_tr.append(
            "<tr>"
            f"<td>{r['date']}</td><td>{r['board']}</td><td>{direction}</td>"
            f"<td>{net_cell}</td>"
            f"<td>{r['up']}↑ {r['down']}↓</td>"
            f'<td class="{_cls(r["index_chg"])}">{_fmt(r["index_chg"], "%", 1)}</td>'
            "</tr>"
        )
        hsgt_md.append(
            f"| {r['date']} | {r['board']} | {direction} | "
            f"{_fmt(net, ' 亿') if net is not None else '已停披露'} | "
            f"{r['up']}↑ {r['down']}↓ | {_fmt(r['index_chg'], '%', 1)} |"
        )

    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1080px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 24px 0 8px; }
.meta { color: #86909c; font-size: 12px; margin-bottom: 16px; }
.card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; }
th { background: #fafafa; color: #666; font-weight: 600; }
th:first-child, td:first-child { text-align: left; }
.up { color: #e02e24; } .down { color: #00a870; }
.footer { color: #86909c; font-size: 12px; text-align: center; padding: 16px 0 8px; }
"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>资金面监控 {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>资金面监控</h1>
<div class="meta">{as_of} · 个股主力资金流（东财 push2）· 沪深港通（akshare/东财）· 涨红跌绿 ·
单位：亿元</div>
<h2>个股主力资金流</h2>
<div class="card"><table>
<tr><th>标的</th><th>日期</th><th>主力净流入</th><th>超大单</th><th>大单</th><th>中单</th><th>小单</th></tr>
{''.join(tr) if tr else '<tr><td colspan="7" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<h2>沪深港通概要</h2>
<div class="card"><table>
<tr><th>日期</th><th>通道</th><th>方向</th><th>成交净买额</th><th>涨跌家数</th><th>指数涨跌</th></tr>
{''.join(hsgt_tr) if hsgt_tr else '<tr><td colspan="6" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<div class="footer">北向净买入额度自 2024-08 起停止披露（监管调整）。资金流为公开数据统计，不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 资金面监控 {as_of}
date: {as_of}
tags: [资金, 北向]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 资金面监控 {as_of}

## 个股主力资金流（亿元）

{chr(10).join(md_rows) if md_rows else "无数据。"}

## 沪深港通概要

| 日期 | 通道 | 方向 | 成交净买额 | 涨跌家数 | 指数涨跌 |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(hsgt_md) if hsgt_md else "无数据。"}

> 北向净买入额度自 2024-08 起停止披露（监管调整）。不构成投资建议。
"""
    return html, md
