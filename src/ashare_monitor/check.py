"""个股资料完整性体检：全维度检查数据是否齐备。

维度：K线历史/基本面/估值/筹码/基金/研报/事件/诉讼/工商档案/官网/
产销/行业/北向/增减持/质押/龙虎榜/大宗/研发(arXiv/HF)。
每维度返回状态：OK（完整）/ WARN（部分/受限）/ MISSING（缺失）+ 原因。
网络维度失败如实标注（数据源受限/反爬/停披露等），不硬凑。

声明：检查结果基于公开数据可达性，不构成投资建议（见 signals.DISCLAIMER）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class CheckItem:
    name: str
    status: str        # OK / WARN / MISSING
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _ok(name: str, detail: str = "") -> CheckItem:
    return CheckItem(name, "OK", detail)


def _warn(name: str, detail: str = "") -> CheckItem:
    return CheckItem(name, "WARN", detail)


def _miss(name: str, detail: str = "") -> CheckItem:
    return CheckItem(name, "MISSING", detail)


def check_stock(code: str, name: str, market: str, cfg=None) -> list[CheckItem]:
    """体检单只标的（股票/港股/数字货币）。"""
    checks: list[CheckItem] = []

    if market == "crypto":
        return _check_crypto(code, name, checks)
    if market == "us":
        return _check_us(code, name, checks)

    # 1. K 线历史（本地）
    try:
        from .storage import load_klines

        rows = load_klines(code, market)
        if len(rows) < 100:
            checks.append(_warn("K线历史", f"仅 {len(rows)} 根，建议 backfill"))
        else:
            last = rows[-1]["date"]
            gap = (datetime.now()
                   - datetime.strptime(last, "%Y-%m-%d")).days
            fresh = "新鲜" if gap <= 5 else f"滞后 {gap} 天"
            checks.append(_ok("K线历史",
                              f"{len(rows)} 根（{rows[0]['date']} ~ {last}，{fresh}）"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("K线历史", f"无本地数据：{exc}"))

    if market != "ashare":
        # 港股：画像接口（统一）/ 公告 / 研报 / 事件 / 诉讼 / 工商 / 官网 / 择时 / 行业
        prof = None
        try:
            from .asset import build_profile

            prof = build_profile(code, name, "hk", cfg)
            detail = []
            if prof.extra.get("roe") is not None:
                detail.append(f"ROE {prof.extra['roe']:.1f}%")
            if prof.growth_rate is not None:
                detail.append(f"净利同比 {prof.growth_rate:+.1f}%")
            if prof.valuation.get("pe_ttm"):
                detail.append(f"PE≈{prof.valuation['pe_ttm']:.1f}")
            if detail:
                checks.append(_ok("基本面", "；".join(detail)))
            else:
                checks.append(_warn("基本面", prof.note or "画像字段缺失"))
        except Exception as exc:  # noqa: BLE001
            checks.append(_miss("基本面", f"获取失败：{str(exc)[:40]}"))
        if prof is not None and prof.valuation.get("pe_ttm"):
            checks.append(_ok("估值(近似)",
                              f"PE≈{prof.valuation['pe_ttm']:.1f}"))
        else:
            checks.append(_warn("估值(近似)", "EPS 或现价缺失"))
        try:
            from .announcements import fetch_announcements

            anns = fetch_announcements(code, limit=5)
            checks.append(_ok("公告", f"{len(anns)} 条" if anns
                              else "东财接口港股公告暂不可用（如实）"))
        except Exception as exc:  # noqa: BLE001
            checks.append(_warn("公告", f"获取失败：{str(exc)[:40]}"))
        try:
            from .announcements import fetch_research_reports

            reps = fetch_research_reports(code, days=90, limit=5)
            checks.append(_ok("研报", f"近90天 {len(reps)} 篇" if reps
                              else "东财研报接口港股暂不可用（如实）"))
        except Exception as exc:  # noqa: BLE001
            checks.append(_warn("研报", f"获取失败：{str(exc)[:40]}"))
        try:
            from .events import fetch_events

            evs = fetch_events(code, "hk", days=60)
            checks.append(_ok("事件日历", f"未来 60 天 {len(evs)} 项" if evs
                              else "港股事件源暂不可用（如实）"))
        except Exception as exc:  # noqa: BLE001
            checks.append(_warn("事件日历", f"获取失败：{str(exc)[:40]}"))
        try:
            from .litigation import scan_watchlist_lawsuits

            lits = scan_watchlist_lawsuits(cfg, days=365)
            lits = [l for l in lits if l.code == code]
            checks.append(_ok("诉讼监控", f"{len(lits)} 条" if lits
                              else "港股无公开诉讼记录（开曼实体，如实）"))
        except Exception as exc:  # noqa: BLE001
            checks.append(_warn("诉讼监控", f"获取失败：{str(exc)[:40]}"))
        try:
            from .profile import fetch_profile

            p = fetch_profile(code, "hk")
            if p.legal_person or p.full_name:
                checks.append(_ok("工商档案", p.full_name or p.name))
            else:
                checks.append(_warn("工商档案", "港股开曼实体巨潮无档案（如实）"))
        except Exception:  # noqa: BLE001
            checks.append(_warn("工商档案", "获取失败（开曼实体）"))
        try:
            from .site import site_links

            sl = site_links(cfg, code, name)
            if sl.website:
                checks.append(_ok("官网链接", sl.website))
            else:
                checks.append(_warn("官网链接", "无官网（可配置 sites 段）"))
        except Exception:  # noqa: BLE001
            checks.append(_warn("官网链接", "获取失败"))
        try:
            from .timing import scan_timing

            sigs = scan_timing(rows, code, name, "hk")
            checks.append(_ok("择时信号", "；".join(s.label for s in sigs[:3])
                              if sigs else "无信号"))
        except Exception:  # noqa: BLE001
            checks.append(_warn("择时信号", "计算失败"))
        try:
            from .industry import fetch_industry

            ind = fetch_industry()
            hit = next((x for x in ind.man_rank
                        if x["name"] and (name[:2] in x["name"]
                                          or x["name"][:2] in name)), None)
            checks.append(_ok("行业数据", f"厂商第 {hit['rank']} 名（{hit['cur']:.1f}万）"
                              if hit else "乘联会 TOP10 榜无该司（如实）"))
        except Exception as exc:  # noqa: BLE001
            checks.append(_miss("行业数据", f"获取失败：{str(exc)[:40]}"))
        return checks

    # 2+3. 基本面与估值（统一画像接口）
    try:
        from .asset import build_profile

        prof = build_profile(code, name, "ashare", cfg)
        if prof.extra.get("roe") is not None:
            detail = f"ROE {prof.extra['roe']:.1f}%"
            if prof.growth_rate is not None:
                detail += f" 净利同比 {prof.growth_rate:+.1f}%（{prof.extra.get('report_date', '')}）"
            checks.append(_ok("基本面", detail))
        else:
            checks.append(_warn("基本面", prof.note or "财报字段缺失"))
        if prof.valuation.get("pe_ttm") is not None:
            checks.append(_ok("估值分位",
                              f"PE {prof.valuation['pe_ttm']:.1f}"
                              f"(分位{prof.valuation.get('pe_pct', 0):.0f}%) "
                              f"PB {prof.valuation.get('pb_mrq', 0):.2f}"
                              f"(分位{prof.valuation.get('pb_pct', 0):.0f}%)"))
        else:
            checks.append(_miss("估值分位", "无数据"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("基本面", f"获取失败：{str(exc)[:40]}"))
        checks.append(_miss("估值分位", f"获取失败：{str(exc)[:40]}"))

    # 4. 筹码（十大股东+户数）
    try:
        from .holders import concentration_status, fetch_top10

        top10, report_date = fetch_top10(code, market)
        state, desc = concentration_status(code)
        if top10:
            checks.append(_ok("筹码",
                              f"十大股东 {len(top10)} 家（{report_date}）；"
                              f"户数{state or '未知'}"))
        else:
            checks.append(_miss("筹码", "十大股东无数据"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("筹码", f"获取失败：{str(exc)[:40]}"))

    # 5. 基金持仓
    try:
        if cfg is not None:
            from .buyer import fetch_fund_holds

            holds = fetch_fund_holds(cfg, codes=[code])
            if holds:
                h = holds[0]
                checks.append(_ok("基金持仓",
                                  f"{h.fund_count} 家，{h.change} {h.change_ratio:+.1f}%"
                                  if h.change_ratio is not None
                                  else f"{h.fund_count} 家"))
            else:
                checks.append(_miss("基金持仓", "不在基金重仓名单"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("基金持仓", f"获取失败：{str(exc)[:40]}"))

    # 6. 研报
    try:
        from .announcements import fetch_research_reports

        reps = fetch_research_reports(code, days=90, limit=5)
        if reps:
            eps = reps[0].get("eps_this_year")
            checks.append(_ok("研报",
                              f"近90天 {len(reps)} 篇（{reps[0].get('org','')}，"
                              f"EPS预测 {eps}）"))
        else:
            checks.append(_warn("研报", "近 90 天无研报覆盖"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("研报", f"获取失败：{str(exc)[:40]}"))

    # 7. 事件日历
    try:
        from .events import fetch_events

        evs = fetch_events(code, market, days=60)
        if evs is not None:
            checks.append(_ok("事件日历", f"未来 60 天 {len(evs)} 项"))
        else:
            checks.append(_miss("事件日历", "无数据"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("事件日历", f"获取失败：{str(exc)[:40]}"))

    # 8. 诉讼
    try:
        from .litigation import scan_watchlist_lawsuits

        lits = scan_watchlist_lawsuits(cfg, days=365)
        lits = [l for l in lits if l.code == code]
        if lits is not None:
            checks.append(_ok("诉讼监控", f"{len(lits)} 条记录"))
        else:
            checks.append(_miss("诉讼监控", "无数据"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("诉讼监控", f"获取失败：{str(exc)[:40]}"))

    # 9. 工商档案
    try:
        from .profile import fetch_profile

        p = fetch_profile(code, market)
        if p.legal_person:
            checks.append(_ok("工商档案",
                              f"{p.full_name or p.name}｜法人 {p.legal_person}"
                              f"｜注册资金 {p.reg_capital / 1e4:.0f} 亿"
                              if p.reg_capital else p.full_name or p.name))
        else:
            checks.append(_miss("工商档案", "；".join(p.errors) or "无档案"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("工商档案", f"获取失败：{str(exc)[:40]}"))

    # 10. 官网
    try:
        from .site import site_links

        sl = site_links(cfg, code, name)
        if sl.website:
            checks.append(_ok("官网链接", sl.website))
        else:
            checks.append(_warn("官网链接", "无官网（可配置 sites 段）"))
    except Exception:  # noqa: BLE001
        checks.append(_warn("官网链接", "获取失败"))

    # 11. 产销快报
    try:
        from .sector import parse_sales, scan_sales

        sales = scan_sales(cfg, codes=[code])
        if sales:
            latest = sales[0]
            if latest.sales is not None:
                checks.append(_ok("产销快报",
                                  f"{latest.month} {latest.sales:.2f} 万"))
            else:
                checks.append(_warn("产销快报",
                                    f"{latest.month}（销量在正文，沙箱提取受限）"))
        else:
            checks.append(_warn("产销快报", "近期无产销快报"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("产销快报", f"获取失败：{str(exc)[:40]}"))

    # 12. 行业数据（含厂商份额）
    try:
        from .industry import fetch_industry

        ind = fetch_industry()
        byd = next((x for x in ind.man_rank
                    if x["name"] and "比亚迪" in x["name"]), None)
        if byd:
            checks.append(_ok("行业数据",
                              f"渗透率 {ind.penetration.get(max(ind.penetration), 0):.1f}%；"
                              f"厂商第 {byd['rank']} 名"))
        else:
            checks.append(_warn("行业数据", "乘联会厂商榜无该司"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("行业数据", f"获取失败：{str(exc)[:40]}"))

    # 13. 北向
    try:
        from .north import fetch_north

        nh = fetch_north(code)
        if nh:
            latest = nh[0]
            checks.append(_ok("北向持股",
                              f"{latest.hold_ratio:.2f}%（最新 {latest.date}）"))
        else:
            checks.append(_miss("北向持股", "无数据"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("北向持股", f"获取失败：{str(exc)[:40]}"))

    # 14. 增减持/回购
    try:
        from .corp_events import scan_corp_events

        evs = scan_corp_events(cfg, codes=[code])
        if evs:
            kinds = {e.event_type for e in evs}
            checks.append(_ok("增减持回购", "近 30 天 " + "、".join(kinds)))
        else:
            checks.append(_ok("增减持回购", "近 30 天无信号"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("增减持回购", f"获取失败：{str(exc)[:40]}"))

    # 15. 质押
    try:
        from .pledge import fetch_pledges

        today = datetime.now().strftime("%Y%m%d")
        rows = []
        try:
            rows = fetch_pledges(today)
        except Exception:  # noqa: BLE001
            rows = []
        hits = [r for r in rows if r.code == code]
        checks.append(_ok("股权质押", f"今日 {len(hits)} 笔公告" if hits
                          else "今日无质押公告"))
    except Exception:  # noqa: BLE001
        checks.append(_warn("股权质押", "数据源受限"))

    # 15a. 工商画像（天眼查导入，company_profiles）
    try:
        from .import_data import get_all_company_profiles, get_profile_meta

        profiles = get_all_company_profiles()
        meta = get_profile_meta()
        match = None
        match_key = None
        for full_name, prof in profiles.items():
            if name in full_name or full_name in name:
                match = prof
                match_key = full_name
                break
        if match:
            detail = []
            scale = match.get("规模")
            if scale:
                detail.append(f"规模 {scale}")
            tags = match.get("标签")
            if isinstance(tags, list) and tags:
                detail.append(f"标签 {'/'.join(tags[:3])}")
            labels = match.get("标签") if isinstance(match.get("标签"), str) else None
            est = match.get("成立日期") or match.get("成立时间")
            if est:
                detail.append(f"成立 {str(est)[:10]}")
            status = match.get("经营状态")
            if status:
                detail.append(status)
            # 数据血缘 + 新鲜度（元数据）
            m = (meta.get(match_key) or {}) if match_key else {}
            src = m.get("source") or match.get("数据源") or "天眼查"
            detail.append(f"来源 {src}")
            upd = m.get("updated")
            if upd:
                try:
                    days = (__import__("datetime").date.today()
                            - __import__("datetime").date.fromisoformat(upd)).days
                    if days > 90:
                        detail.append(f"{days} 天前更新，建议回补")
                    else:
                        detail.append(f"{days} 天前更新")
                except ValueError:
                    pass
            if detail:
                checks.append(_ok("工商画像", "；".join(detail)))
            else:
                checks.append(_ok("工商画像", "已导入"))
    except Exception:  # noqa: BLE001
        pass
    # 15a2. 知识产权（智慧芽导入，ip_assets，含质量/新鲜度/血缘）
    try:
        from collections import Counter

        from .import_data import get_all_ip_assets, get_ip_meta

        ip_assets = get_all_ip_assets()
        ip_meta = get_ip_meta()
        ip_match = None
        ip_key = None
        for full_name, ip in ip_assets.items():
            if name in full_name or full_name in name:
                ip_match = ip
                ip_key = full_name
                break
        if ip_match:
            np_ = len(ip_match.get("patents") or [])
            na_ = len(ip_match.get("papers") or [])
            detail = [f"专利 {np_} 件"]
            if na_:
                detail.append(f"论文 {na_} 篇")
            pats = ip_match.get("patents") or []
            if pats:
                # 专利质量：法律状态分布 + IPC 技术分布 + 近 3 年新增
                status_cnt = Counter(p.get("legal_status") or "unknown"
                                     for p in pats)
                act = status_cnt.get("active", 0)
                pend = status_cnt.get("pending", 0)
                if act or pend:
                    detail.append(f"有效 {act}/申请中 {pend}")
                ipc_cnt = Counter((p.get("ipc") or "")[:4]
                                  for p in pats if p.get("ipc"))
                if ipc_cnt:
                    top_ipc = ipc_cnt.most_common(1)[0][0]
                    detail.append(f"技术 {top_ipc} 为主")
                recent = sum(1 for p in pats
                             if str(p.get("date") or "")[:4] >= "2023")
                if recent:
                    detail.append(f"近3年 {recent} 件")
                latest = max(pats, key=lambda x: str(x.get("date") or ""))
                detail.append(f"最新 {latest.get('date', '')[:10]} "
                              f"{str(latest.get('title', ''))[:18]}")
            # 数据血缘 + 新鲜度
            m = (ip_meta.get(ip_key) or {}) if ip_key else {}
            src = m.get("source") or "智慧芽"
            detail.append(f"来源 {src}")
            upd = m.get("updated")
            if upd:
                try:
                    days = (__import__("datetime").date.today()
                            - __import__("datetime").date.fromisoformat(upd)).days
                    detail.append("30 天内更新" if days <= 30
                                  else f"{days} 天前更新，建议回补")
                except ValueError:
                    pass
            checks.append(_ok("知识产权", "；".join(detail)))
    except Exception:  # noqa: BLE001
        pass
    # 15b. 两融（融资余额与趋势）
    try:
        from .a_stock_data import margin_trading

        rows = margin_trading(code)
        if rows:
            latest, prev = rows[0], (rows[1] if len(rows) > 1 else None)
            rzye = (latest["rzye"] or 0) / 1e8
            detail = f"融资余额 {rzye:.1f} 亿"
            if prev and prev.get("rzye"):
                chg = ((latest["rzye"] or 0) - (prev["rzye"] or 0)) / 1e8
                detail += f"（较前日 {chg:+.1f} 亿）"
            if latest.get("rzmre"):
                detail += f" 买入 {latest['rzmre'] / 1e8:.1f} 亿"
            detail += "（来源 东财）"
            checks.append(_ok("两融", detail))
        else:
            checks.append(_warn("两融", "数据源受限（如实）"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_warn("两融", f"获取失败：{str(exc)[:30]}"))
    # 15c. 解禁（未来 90 天）
    try:
        from .a_stock_data import lockup_expiry

        data = lockup_expiry(code)
        upcoming = data.get("upcoming") or []
        if upcoming:
            first = upcoming[0]
            detail = f"未来 90 天 {len(upcoming)} 批，最近 {first['date']}"
            if first.get("ratio_pct"):
                detail += f"（占比 {first['ratio_pct']}%）"
            detail += "（来源 东财）"
            checks.append(_warn("解禁", detail))
        else:
            checks.append(_ok("解禁", "未来 90 天无解禁（来源 东财）"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_warn("解禁", f"获取失败：{str(exc)[:30]}"))
    # 16. 龙虎榜
    try:
        from .lhb import scan_lhb

        rows = scan_lhb(cfg, days=10)
        hits = [r for r in rows if r.code == code]
        checks.append(_ok("龙虎榜", f"近 10 天上榜 {len(hits)} 次" if hits
                          else "近 10 天未上榜"))
    except Exception:  # noqa: BLE001
        checks.append(_warn("龙虎榜", "数据源受限"))

    # 17. 大宗交易
    try:
        from .block import scan_block_trades

        rows = scan_block_trades(cfg, days=10)
        hits = [r for r in rows if r.code == code]
        checks.append(_ok("大宗交易", f"近 10 天 {len(hits)} 笔" if hits
                          else "近 10 天无大宗交易"))
    except Exception:  # noqa: BLE001
        checks.append(_warn("大宗交易", "数据源受限"))

    # 18. 研发（arXiv/HF）
    try:
        from .arxiv import fetch_arxiv

        papers = fetch_arxiv(f"all:\"BYD Auto\"", max_results=5)
        checks.append(_ok("研发(arXiv)", f"近期 {len(papers)} 篇论文" if papers
                          else "近期无论文"))
    except Exception:  # noqa: BLE001
        checks.append(_warn("研发(arXiv)", "数据源受限"))

    return checks


def build_check_report(code: str, name: str, checks: list[CheckItem],
                       as_of: str | None = None) -> tuple[str, str]:
    """生成体检报告（HTML, Markdown）。"""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")

    def _color(s: str) -> str:
        return {"OK": "#00a870", "WARN": "#b7950b", "MISSING": "#e02e24"}.get(s, "")

    stats = {"OK": sum(1 for c in checks if c.status == "OK"),
             "WARN": sum(1 for c in checks if c.status == "WARN"),
             "MISSING": sum(1 for c in checks if c.status == "MISSING")}
    tr = []
    md_rows = ["| 维度 | 状态 | 说明 |", "| --- | --- | --- |"]
    for c in checks:
        color = _color(c.status)
        tr.append(
            "<tr>"
            f"<td>{c.name}</td>"
            f'<td><span style="color:{color};font-weight:600">{c.status}</span></td>'
            f'<td style="text-align:left">{c.detail}</td>'
            "</tr>"
        )
        md_rows.append(f"| {c.name} | {c.status} | {c.detail} |")

    css = """
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f7f8fa; color: #1f2329; margin: 0; }
.container { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
.meta { color: #86909c; font-size: 12px; margin-bottom: 16px; }
.card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; }
th { background: #fafafa; color: #666; font-weight: 600; }
th:first-child, td:first-child { text-align: left; }
.footer { color: #86909c; font-size: 12px; text-align: center; padding: 16px 0 8px; }
"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>资料体检 {name}({code}) {as_of}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>个股资料完整性体检：{name}（{code}）</h1>
<div class="meta">{as_of} · OK {stats['OK']} / WARN {stats['WARN']} / MISSING {stats['MISSING']} ·
检查基于公开数据可达性，缺失项如实标注原因</div>
<div class="card"><table>
<tr><th>维度</th><th>状态</th><th style="text-align:left">说明</th></tr>
{''.join(tr) if tr else '<tr><td colspan="3" style="text-align:center;color:#86909c">无数据</td></tr>'}
</table></div>
<div class="footer">不构成投资建议。</div>
</div>
</body>
</html>"""

    md = f"""---
title: 资料体检 {name}({code}) {as_of}
date: {as_of}
tags: [体检, 完整性]
generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}
---
# 个股资料体检：{name}（{code}）

OK {stats['OK']} / WARN {stats['WARN']} / MISSING {stats['MISSING']}

{chr(10).join(md_rows) if md_rows else "无数据。"}

> 不构成投资建议。
"""
    return html, md


def _check_crypto(code: str, name: str, checks: list) -> list:
    """数字货币体检：行情 / 画像（代币经济）/ K线技术面。"""
    # 1. 实时行情（Binance，已接入）
    try:
        from .providers.binance import BinanceProvider

        p = BinanceProvider()
        qs = p.fetch([code])
        if qs:
            q = qs[0]
            checks.append(_ok("实时行情",
                              f"{q.price:,.2f} USDT（24h {q.change_pct:+.2f}%）"
                              f"｜成交额 {q.turnover / 1e6:,.0f} 万"))
        else:
            checks.append(_miss("实时行情", "Binance 无该交易对"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("实时行情", f"获取失败：{str(exc)[:40]}"))
    # 2. 代币经济画像（CoinGecko）
    try:
        from .asset import build_profile

        prof = build_profile(code, name, "crypto")
        if prof.status == "OK":
            notes = []
            if prof.market_cap:
                notes.append(f"市值 ${prof.market_cap / 1e9:.1f}B")
            if prof.supply_total:
                notes.append(f"总供给 {prof.supply_total / 1e6:.0f}M")
            if prof.extra.get("circulation_pct"):
                notes.append(f"流通 {prof.extra['circulation_pct']:.0f}%")
            if prof.valuation.get("nvt_approx"):
                notes.append(f"NVT≈{prof.valuation['nvt_approx']}")
            checks.append(_ok("代币经济", "；".join(notes)))
            checks.append(_ok("估值(NVT)", f"NVT≈{prof.valuation['nvt_approx']}"
                              if prof.valuation.get("nvt_approx") else "数据缺失"))
        else:
            checks.append(_warn("代币经济", prof.note))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("代币经济", f"获取失败：{str(exc)[:40]}"))
    # 3. K 线技术面（Binance 直拉；open_time 为 int 毫秒时间戳）
    try:
        from datetime import datetime, timezone

        from .providers.binance import fetch_klines

        raw = fetch_klines(code, days=200)
        if raw:
            closes = [float(k[4]) for k in raw]
            last_date = datetime.fromtimestamp(
                int(raw[-1][0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            checks.append(_ok("K线(币安)",
                              f"{len(raw)} 根 ~ {last_date}（最新 {closes[-1]:,.2f}）"))
            from .timing import scan_timing

            rows = [{"date": datetime.fromtimestamp(
                        int(k[0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                     "close": float(k[4]), "open": float(k[1]),
                     "high": float(k[2]), "low": float(k[3]),
                     "volume": float(k[5])}
                    for k in raw]
            sigs = scan_timing(rows, code, name, "crypto")
            checks.append(_ok("择时信号",
                              "；".join(s.label for s in sigs[:3]) if sigs
                              else "无信号"))
        else:
            checks.append(_miss("K线(币安)", "无数据"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("K线(币安)", f"获取失败：{str(exc)[:40]}"))
    return checks


def _check_us(code: str, name: str, checks: list) -> list:
    """美股体检：行情 / K线历史 / 技术面 / 基本面（受限如实）。"""
    # 1. 实时行情
    try:
        from .quotes import fetch_spot_quotes

        qs, src = fetch_spot_quotes([code], market="us")
        if qs:
            q = qs[0]
            checks.append(_ok("实时行情",
                              f"${q.price:,.2f}（{q.change_pct:+.2f}%）"
                              f"｜源 {src}"))
        else:
            checks.append(_miss("实时行情", "无数据"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("实时行情", f"获取失败：{str(exc)[:40]}"))
    # 2. K 线历史（本地）
    try:
        from .storage import load_klines

        rows = load_klines(code, "us")
        if rows:
            last = rows[-1]["date"]
            checks.append(_ok("K线历史",
                              f"{len(rows)} 根（{rows[0]['date']} ~ {last}）"))
            from .timing import scan_timing

            sigs = scan_timing(rows, code, name, "us")
            checks.append(_ok("择时信号",
                              "；".join(s.label for s in sigs[:3]) if sigs
                              else "无信号"))
        else:
            checks.append(_warn("K线历史", "未回填（backfill NVDA --market us）"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("K线历史", f"获取失败：{str(exc)[:40]}"))
    # 3. 基本面（东财美股财务指标）
    try:
        from .asset import build_profile

        prof = build_profile(code, name, "us")
        if prof.extra.get("roe") is not None:
            detail = f"ROE {prof.extra['roe']:.1f}%"
            if prof.growth_rate is not None:
                detail += f" 净利同比 {prof.growth_rate:+.1f}%"
            if prof.extra.get("gross_margin") is not None:
                detail += f" 毛利率 {prof.extra['gross_margin']:.1f}%"
            checks.append(_ok("基本面", detail))
        else:
            checks.append(_warn("基本面", prof.note or "美股财务缺失"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_miss("基本面", f"获取失败：{str(exc)[:40]}"))
    # 4. 估值（PE = 市值/年度净利；市值取东财美股行情，沙箱可能不可达）
    try:
        from .asset import build_profile

        prof = build_profile(code, name, "us")
        npf = prof.extra.get("net_profit")
        if npf:
            import akshare as ak

            spot = ak.stock_us_spot_em()
            row = spot[spot["代码"] == code] if spot is not None else None
            if row is not None and len(row):
                mv = row.iloc[0].get("总市值")
                if mv:
                    checks.append(_ok(
                        "估值(近似)",
                        f"PE≈{mv / npf:.1f}（市值 ${mv / 1e12:.2f}T/年度净利）"))
                    return checks
            checks.append(_warn("估值(近似)",
                                "市值需东财美股行情（本机直连通常可用）"))
        else:
            checks.append(_warn("估值(近似)", "净利缺失"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_warn("估值(近似)", f"市值获取失败：{str(exc)[:40]}（本机直连可用）"))
    return checks
