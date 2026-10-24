# -*- coding: utf-8 -*-
"""ashare-monitor 数据积累体检报告生成器（health-YYYY-MM-DD.html）。

供体检自动化（WorkBuddy automation 8e92d3cf）与人工调用：
    .venv/Scripts/python.exe scripts/health_report.py                # 全量：查询+写快照+出报告
    .venv/Scripts/python.exe scripts/health_report.py --no-snapshot  # 试跑：只出报告，不动基线
    .venv/Scripts/python.exe scripts/health_report.py --notes n.json # 追加 AI 判定的 incidents/observations

报告格式：监控台风格（钢蓝单强调色 + 语义状态色），数据全部来自实测查询。
规则：探针仅在 A/H 落后 >=1 个交易日时触发（腾讯 fqkline 空 end 形态）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(r"E:\database\sqlite\ashare_monitor.db")
DEFAULT_SNAPSHOT = ROOT / "output" / "health_snapshot.json"
DEFAULT_OUTDIR = ROOT / "output"
DEFAULT_LOGS = ROOT / "logs"
BACKUP_DIR = Path(r"E:\database\backup")
QUEUE_JSON = DEFAULT_OUTDIR / "backfill_queue.json"
CONFIG = ROOT / "config.yaml"
VAULT_INVEST = Path(r"E:\Obsidian\wxb4733\ashare-monitor 库")
VAULT_NOTES = Path(r"E:\Obsidian\wxb4733")

# 本机需绕代理的域（与 daily_backfill_task.bat 口径一致）
NO_PROXY_DOMAINS = "eastmoney.com,sinajs.cn,qq.com,gtimg.cn,cninfo.com.cn"

TABLES = ["klines", "announcements", "research_reports", "financials", "reviews", "paper_history"]
LOG_FILES = [
    "backfill_task.log", "cron_paper_daily.log", "cron_close_review.log",
    "cron_weekly_friday.log", "cron_vault_push_invest.log", "cron_vault_push_notes.log",
    "cron_risk_check.log", "cron_scan_intraday.log", "cron_signal_digest.log",
    "cron_period_daily.log", "cron_period_weekly.log", "cron_period_monthly.log",
    "cron_dividend_weekly.log", "cron_hk_financials.log",
]
ERR_PAT = re.compile(r"ERROR|Traceback|invalid choice|WinError", re.I)


# ---------------------------------------------------------------- utilities
def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def weekdays_between(start_excl: date, end_incl: date) -> list[date]:
    out, d = [], start_excl + timedelta(days=1)
    while d <= end_incl:
        if is_weekday(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def last_weekday_on_or_before(d: date) -> date:
    while not is_weekday(d):
        d -= timedelta(days=1)
    return d


def fmt_cn(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def read_text_guess(path: Path, max_bytes: int = 65536) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            raw = f.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("gbk", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------- collectors
def q_all(cur, sql, args=()):
    return cur.execute(sql, args).fetchall()


def collect_db(db: Path) -> dict:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    cur = con.cursor()
    data: dict = {}
    data["totals"] = {t: q_all(cur, f"SELECT COUNT(*) FROM {t}")[0][0] for t in TABLES}

    data["klines_market"] = {}
    for m, n, mn, mx in q_all(cur, "SELECT market, COUNT(*), MIN(date), MAX(date) FROM klines GROUP BY market"):
        codes = q_all(cur, "SELECT COUNT(DISTINCT code) FROM klines WHERE market=?", (m,))[0][0]
        data["klines_market"][m] = {"rows": n, "min": mn, "max": mx, "codes": codes}
    data["code_max"] = {}
    for m in ("ashare", "hk", "us", "crypto"):
        data["code_max"][m] = {
            r[0]: r[1] for r in q_all(cur, "SELECT code, MAX(date) FROM klines WHERE market=? GROUP BY code", (m,))
        }
    data["ann"] = {r[0]: {"n": r[1], "max": r[2]}
                   for r in q_all(cur, "SELECT code, COUNT(*), MAX(date) FROM announcements GROUP BY code")}
    data["research"] = {r[0]: {"n": r[1], "max": r[2]}
                        for r in q_all(cur, "SELECT code, COUNT(*), MAX(date) FROM research_reports GROUP BY code")}
    data["fin"] = {r[0]: {"n": r[1], "max": r[2]}
                   for r in q_all(cur, "SELECT code, COUNT(*), MAX(report_date) FROM financials GROUP BY code")}
    data["reviews_max"] = q_all(cur, "SELECT MAX(date) FROM reviews")[0][0]
    data["nav"] = q_all(cur, "SELECT date, nav FROM paper_history ORDER BY date")
    data["ph_weekend"] = q_all(
        cur, "SELECT date FROM paper_history WHERE CAST(strftime('%w', date) AS INT) IN (0,6)")
    con.close()
    return data


def parse_watchlist() -> list[dict]:
    text = CONFIG.read_text(encoding="utf-8", errors="replace") if CONFIG.is_file() else ""
    m = re.search(r"^watchlist:\s*$(.*?)(?=^\w|\Z)", text, re.M | re.S)
    block = m.group(1) if m else ""
    out = []
    for code_m in re.finditer(r'-\s*code:\s*"([\w.]+)"', block):
        code = code_m.group(1)
        tail = block[code_m.end():code_m.end() + 300]
        name_m = re.search(r'name:\s*"([^"]+)"', tail)
        mkt_m = re.search(r"market:\s*(\w+)", tail)
        out.append({"code": code, "name": name_m.group(1) if name_m else code,
                    "market": mkt_m.group(1) if mkt_m else "ashare"})
    return out


def parse_queue() -> list[dict]:
    try:
        q = json.loads(QUEUE_JSON.read_text(encoding="utf-8"))
        return q if isinstance(q, list) else []
    except (OSError, ValueError):
        return []


def collect_reports() -> dict:
    out = {}
    pats = {
        "review_html": r"review-(\d{4}-\d{2}-\d{2})\.html",
        "daily_html": r"daily-(\d{4}-\d{2}-\d{2})\.html",
        "weekly_html": r"weekly-(\d{4}-\d{2}-\d{2})\.html",
        "report_weekly_html": r"report-weekly-(\d{4}-\d{2}-\d{2})\.html",
        "monthly_html": r"monthly-(\d{4}-\d{2}-\d{2})\.html",
    }
    for key, pat in pats.items():
        dates = sorted(m.group(1) for f in os.listdir(DEFAULT_OUTDIR)
                       if (m := re.fullmatch(pat, f)))
        out[key] = {"count": len(dates), "dates": dates, "latest": dates[-1] if dates else None}
    vault = VAULT_INVEST / "A股复盘"
    md = sorted(f[7:17] for f in os.listdir(vault)
                if (m := re.fullmatch(r"review-(\d{4}-\d{2}-\d{2})\.md", f))) if vault.is_dir() else []
    out["review_vault_md"] = {"count": len(md), "latest": md[-1] if md else None}
    return out


def collect_backups() -> dict:
    if not BACKUP_DIR.is_dir():
        return {"count": 0, "latest": None, "latest_mtime": None}
    files = sorted(BACKUP_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime)
    latest = files[-1] if files else None
    return {"count": len(files),
            "latest": latest.name if latest else None,
            "latest_mtime": fmt_cn(datetime.fromtimestamp(latest.stat().st_mtime)) if latest else None}


def collect_logs() -> list[dict]:
    rows = []
    for name in LOG_FILES + sorted(f for f in os.listdir(DEFAULT_LOGS)
                                   if f.startswith("queue_backfill") and f.endswith(".log")):
        p = DEFAULT_LOGS / name
        if not p.is_file():
            rows.append({"name": name, "exists": False})
            continue
        text = read_text_guess(p)
        lines = [l for l in text.splitlines() if l.strip()]
        errs = [l for l in lines if ERR_PAT.search(l)]
        done = [l for l in lines if "done" in l and "===" in l]
        rows.append({"name": name, "exists": True,
                     "mtime": fmt_cn(datetime.fromtimestamp(p.stat().st_mtime)),
                     "last_done": done[-1][:120] if done else (lines[-1][:120] if lines else ""),
                     "err_count": len(errs), "err_tail": errs[-2:]})
    return rows


def collect_tasks(tmpdir: Path) -> list[dict]:
    ps_out = tmpdir / "_sched_tasks.txt"
    script = (
        "$t=Get-ScheduledTask -TaskPath '\\' | Where-Object { $_.TaskName -like 'am-*' "
        "-or $_.TaskName -like 'ashare-monitor-*' } | Sort-Object TaskName | ForEach-Object "
        "{ $i = $_ | Get-ScheduledTaskInfo; '{0}|{1}|{2}|{3}|{4}' -f $_.TaskName, $_.State, "
        "$i.LastRunTime, $i.LastTaskResult, $i.NextRunTime }; "
        f"$t | Out-File -FilePath '{ps_out.as_posix()}' -Encoding utf8"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       capture_output=True, timeout=60)
        rows = []
        for line in ps_out.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 5 or not parts[0]:
                continue
            try:
                result = int(parts[3])
            except ValueError:
                result = -1
            rows.append({"name": parts[0], "state": parts[1], "last_run": parts[2],
                         "result": result, "next_run": parts[4]})
        return rows
    except (OSError, subprocess.SubprocessError):
        return []


def collect_repos() -> dict:
    def git(repo: Path, *args: str) -> str:
        try:
            r = subprocess.run(["git", "-C", str(repo), *args],
                               capture_output=True, timeout=30, encoding="utf-8", errors="replace")
            return (r.stdout or "").strip()[:200] or (r.stderr or "").strip()[:200]
        except OSError:
            return "ERR"
    out = {}
    for key, path in (("invest", VAULT_INVEST), ("notes", VAULT_NOTES)):
        out[key] = {"path": str(path), "head": git(path, "rev-parse", "--short", "HEAD"),
                    "remote": git(path, "rev-parse", "--short", "origin/main"),
                    "dirty": bool(git(path, "status", "--porcelain"))}
    return out


def probe_tencent(secid: str, hk: bool) -> str | None:
    """空 end 形态探针（带 end 会漏当日 bar）。返回源侧最新 YYYY-MM-DD。"""
    os.environ.setdefault("NO_PROXY", NO_PROXY_DOMAINS)
    host = "hkfqkline" if hk else "fqkline"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/{host}/get?param={secid},day,,,5,qfq"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        node = data.get("data", {}).get(secid, {})
        bars = node.get("qfqday") or node.get("day") or []
        return bars[-1][0] if bars else None
    except (OSError, ValueError, KeyError, IndexError):
        return None


# ---------------------------------------------------------------- analysis
def analyze(db_data: dict, reports: dict, tasks: list[dict], backups: dict,
            repos: dict, logs: list[dict], today: date, now: datetime) -> dict:
    a: dict = {"freshness": {}, "findings": [], "probe": {}}

    # --- A/H：最近已收盘交易日（盘前/盘中取上一工作日，15:05 后取今日）
    cutoff = now.replace(hour=15, minute=5, second=0, microsecond=0)
    boundary = today if (is_weekday(today) and now >= cutoff) else today - timedelta(days=1)
    expected_ah = last_weekday_on_or_before(boundary)
    for mkt, secid, hk in (("ashare", "sh600036", False), ("hk", "hk01211", True)):
        db_max = db_data["klines_market"].get(mkt, {}).get("max")
        if not db_max:
            a["freshness"][mkt] = {"lag": None, "note": "库内无数据"}
            continue
        db_max_d = date.fromisoformat(db_max)
        lag = len(weekdays_between(db_max_d, expected_ah))
        note = f"{db_data['klines_market'][mkt]['codes']} 只到 {db_max}"
        if lag >= 1:
            src = probe_tencent(secid, hk)
            a["probe"][mkt] = src
            if src and src > db_max:
                a["freshness"][mkt] = {"lag": lag, "note": f"{note}，腾讯源已有 {src} → 真实缺口"}
            else:
                a["freshness"][mkt] = {"lag": 0, "note": f"{note}；源侧最新不超前（节假日休市判定），实测 {src or '未取到'}"}
                lag = 0
        else:
            a["freshness"][mkt] = {"lag": lag, "note": f"{note}，零落后"}
        if lag > 3:
            a["findings"].append({"level": "p1",
                                  "title": f"{mkt} K 线落后 {lag} 个交易日（>{3} 阈值）",
                                  "detail": f"库内最新 {db_max}，预期 {expected_ah}"})

    # --- us / crypto：自然日
    exp_us = last_weekday_on_or_before(today - timedelta(days=1))
    us_max = db_data["klines_market"].get("us", {}).get("max")
    us_lag = (exp_us - date.fromisoformat(us_max)).days if us_max else None
    a["freshness"]["us"] = {"lag": us_lag, "note": f"NVDA 到 {us_max}；美股收盘在北京凌晨、今日 15:35 归档，1 自然日时序差属预期"}
    exp_cr = today - timedelta(days=1)
    cr_max = db_data["klines_market"].get("crypto", {}).get("max")
    cr_lag = (exp_cr - date.fromisoformat(cr_max)).days if cr_max else None
    a["freshness"]["crypto"] = {"lag": cr_lag, "note": f"BTC/ETH 到 {cr_max}"}
    if cr_lag and cr_lag > 1:
        a["findings"].append({"level": "p1", "title": f"crypto 落后 {cr_lag} 自然日",
                              "detail": f"库内最新 {cr_max}，预期 {exp_cr}"})
    if us_lag and us_lag > 2:
        a["findings"].append({"level": "warn", "title": f"美股落后 {us_lag} 自然日（>2）",
                              "detail": f"库内最新 {us_max}，预期 {exp_us}"})

    # --- 日报缺口（工作日轴）
    daily_dates = set(reports["daily_html"]["dates"])
    review_dates = set(reports["review_html"]["dates"])
    horizon_start = date.fromisoformat(reports["daily_html"]["dates"][0]) if reports["daily_html"]["dates"] else today - timedelta(days=60)
    missing_daily = [d.isoformat() for d in weekdays_between(horizon_start - timedelta(days=1), boundary)
                     if d.isoformat() not in daily_dates]
    if missing_daily:
        lvl = "p1" if len(missing_daily) <= 5 else "p1"
        a["findings"].append({"level": lvl, "title": f"日报缺档 {len(missing_daily)} 期",
                              "detail": "、".join(missing_daily[-8:])})

    # --- review 连续性（近 30 天；今日 15:10 前不算当日）
    rev_end = today if now >= now.replace(hour=15, minute=10) else today - timedelta(days=1)
    for i in range(30):
        d = rev_end - timedelta(days=i)
        if d.isoformat() not in review_dates:
            a["findings"].append({"level": "warn", "title": f"近 30 天复盘缺 {d.isoformat()}", "detail": "review 输出缺失"})
            break

    # --- 周五周报连续性（自系列首份起回溯；周五 15:30 前不算当周）
    weekly_dates = set(reports["weekly_html"]["dates"]) | set(reports["report_weekly_html"]["dates"])
    wk_boundary = boundary
    if wk_boundary.weekday() == 4 and now < now.replace(hour=15, minute=30):
        wk_boundary -= timedelta(days=7)
    series_start = (date.fromisoformat(reports["weekly_html"]["dates"][0])
                    if reports["weekly_html"]["dates"] else today - timedelta(days=60))
    d = wk_boundary
    miss_weekly = []
    while d >= series_start:
        if d.weekday() == 4 and d.isoformat() not in weekly_dates:
            miss_weekly.append(d.isoformat())
        d -= timedelta(days=1)
    a["extra"] = {"miss_weekly": sorted(miss_weekly, reverse=True)}
    if miss_weekly:
        a["findings"].append({"level": "warn", "title": f"周五周报缺 {len(miss_weekly)} 期",
                              "detail": "、".join(sorted(miss_weekly, reverse=True))})

    # --- paper_history 缺行（A 股交易日轴，工作日近似）
    if db_data["nav"]:
        last_nav = date.fromisoformat(db_data["nav"][-1][0])
        miss_nav = [d.isoformat() for d in weekdays_between(last_nav, expected_ah)]
        if miss_nav:
            a["findings"].append({"level": "warn", "title": f"净值缺行 {len(miss_nav)} 天（工作日近似）",
                                  "detail": "、".join(miss_nav)})
    if db_data["ph_weekend"]:
        a["findings"].append({"level": "warn", "title": f"paper_history 含 {len(db_data['ph_weekend'])} 行周末数据",
                              "detail": "、".join(r[0] for r in db_data["ph_weekend"][:5])})

    # --- 计划任务
    stuck = [t for t in tasks if t["state"] == "Running"]
    bad = [t for t in tasks if t["result"] not in (0, 267011) and t["state"] != "Running"]
    if stuck:
        names = "、".join(t["name"] for t in stuck)
        a["findings"].append({"level": "p1", "title": f"任务卡 Running：{names}",
                              "detail": "；".join(f"{t['name']} 上次 {t['last_run']} result={t['result']}" for t in stuck)})
    for t in bad:
        a["findings"].append({"level": "warn", "title": f"任务 {t['name']} result={t['result']}",
                              "detail": f"上次 {t['last_run']}（267011=未运行可忽略，此为其他码）"})

    # --- 备份
    if backups["latest_mtime"]:
        age_days = (now - datetime.strptime(backups["latest_mtime"], "%Y-%m-%d %H:%M")).days
        if age_days >= 2:
            a["findings"].append({"level": "warn", "title": f"最新备份已 {age_days} 天（{backups['latest']}）",
                                  "detail": "每日 15:35 任务应产出备份"})

    # --- 双仓同步
    for k, r in repos.items():
        if r["head"] and r["remote"] and r["head"] != r["remote"]:
            a["findings"].append({"level": "warn", "title": f"{k} 仓落后远端（{r['head']} != {r['remote']}）",
                                  "detail": r["path"]})

    # --- 日志 ERROR 级
    for row in logs:
        if row.get("exists") and row.get("err_count"):
            a["findings"].append({"level": "info",
                                  "title": f"{row['name']} 含 {row['err_count']} 条疑似错误行（尾部窗口）",
                                  "detail": row["err_tail"][0][:150] if row["err_tail"] else ""})
    return a


# ---------------------------------------------------------------- snapshot
def write_snapshot(path: Path, db_data: dict, reports: dict, freshness: dict,
                   coverage: dict, backups: dict, repos: dict, nav_last: dict,
                   notes: dict | None, now: datetime) -> None:
    snap = {}
    if path.is_file():
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            snap = {}
    day_key = f"readings_{now.strftime('%Y%m%d')}"
    snap.setdefault(day_key, []).append({
        "at": now.strftime("%H:%M"), "stage": "health_report.py",
        **db_data["totals"]})
    snap["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    snap["totals"] = db_data["totals"]
    snap["market_max_dates"] = {m: v["max"] for m, v in db_data["klines_market"].items()}
    snap["coverage"] = coverage
    snap["reports"] = {k: v["count"] for k, v in reports.items() if isinstance(v, dict)}
    snap["reports"].update({k.replace("_html", "") + "_latest": v["latest"]
                            for k, v in reports.items() if isinstance(v, dict) and v.get("latest")})
    snap["paper_latest_nav"] = nav_last.get("nav")
    snap["paper_history_max_date"] = nav_last.get("date")
    snap["freshness"] = {m: v["lag"] for m, v in freshness.items()}
    snap["repos"] = repos
    if notes:
        for inc in notes.get("incidents", []):
            snap.setdefault("incidents", []).append(inc)
        for ob in notes.get("observations", []):
            snap.setdefault("observations", []).append(ob)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- HTML
CSS = """%(css)s"""  # replaced below at build time; kept for clarity

def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def nav_points(nav: list) -> tuple[str, dict]:
    if not nav:
        return "", {}
    vals = [r[1] for r in nav]
    lo, hi = min(vals) - 0.002, max(vals) + 0.003
    span = hi - lo or 1.0
    n = len(vals)
    pts, peak_i, labels = [], vals.index(max(vals)), {}
    for i, v in enumerate(vals):
        x = 10 + i * (540 / (n - 1))
        y = 115 - (v - lo) / span * 110
        pts.append(f"{x:.1f},{y:.1f}")
    labels = {"polyline": " ".join(pts), "peak": pts[peak_i], "last": pts[-1],
              "peak_d": nav[peak_i][0], "peak_v": f"{vals[peak_i]:.4f}",
              "last_d": nav[-1][0], "last_v": f"{vals[-1]:.4f}",
              "dd": f"{(vals[-1] / max(vals) - 1) * 100:.2f}%",
              "cum": f"{(vals[-1] / vals[0] - 1) * 100:+.2f}%"}
    return labels, {"first_d": nav[0][0], "last_d": nav[-1][0]}


def tier(max_d: str | None, today: date) -> str:
    if not max_d:
        return "stale"
    days = (today - date.fromisoformat(max_d)).days
    return "fresh" if days <= 3 else ("mid" if days <= 20 else "stale")


def render(out_path: Path, db_data: dict, reports: dict, freshness: dict,
           findings: list[dict], backups: dict, tasks: list[dict], logs: list[dict],
           repos: dict, watchlist: list[dict], queue: list[dict], today: date,
           now: datetime, baseline: dict | None, nav_range: dict, extra: dict | None = None) -> None:
    T = db_data["totals"]
    base = (baseline or {}).get("totals", {}) if baseline else {}
    def delta(k):
        if base and k in base:
            d = T[k] - base[k]
            if d > 0:
                return f'<span class="delta up">+{d}</span>'
            return '<span class="delta flat">+0</span>'
        return '<span class="delta flat">基线—</span>'

    p1 = [f for f in findings if f["level"] == "p1"]
    verdict_cls = "p1" if p1 else "ok"
    verdict_txt = f"{len(p1)} 项 P1 · 其余正常" if p1 else "全绿 · 无 P1"

    # KPI
    kpi_names = {"klines": "klines", "announcements": "announcements", "research_reports": "research_reports",
                 "financials": "financials", "reviews": "reviews", "paper_history": "paper_history"}
    kpis = "".join(
        f'<div class="kpi"><div class="name">{k}</div><div class="num">{T[k]:,}</div>{delta(k)}</div>'
        for k in kpi_names)

    # market table
    mrows = ""
    for m, cn in (("ashare", "A 股"), ("hk", "港股"), ("us", "美股"), ("crypto", "加密")):
        v = db_data["klines_market"].get(m, {})
        f = freshness.get(m, {})
        lag = f.get("lag")
        if m in ("ashare", "hk"):
            tag = '<span class="tag ok">零落后</span>' if lag == 0 else (
                f'<span class="tag p1">落后 {lag} 交易日</span>' if lag and lag > 3
                else f'<span class="tag warn">落后 {lag} 交易日</span>' if lag else "")
        elif m == "us":
            tag = '<span class="tag dim">时序差</span>' if lag == 1 else f'<span class="tag warn">落后 {lag} 日</span>'
        else:
            tag = '<span class="tag ok">零落后</span>' if lag == 0 else f'<span class="tag warn">落后 {lag} 日</span>'
        mrows += (f'<tr><td>{cn}</td><td class="mono">{v.get("codes","—")}</td>'
                  f'<td class="mono">{v.get("rows",0):,}</td><td class="mono">{v.get("min","—")} ~</td>'
                  f'<td class="mono">{v.get("max","—")} {tag}</td></tr>')

    # freshness scale rows
    def scale_row(name, sub, lag, note, unit="交易日"):
        pct = min(max((lag or 0), 0) / 4 * 100, 100)
        fill = max(pct, 2.5) if lag is not None else 0
        return (f'<div class="frow"><div class="fname">{name}<small>{sub}</small></div>'
                f'<div class="fscale"><div class="fill" style="width:{fill}%"></div>'
                f'<span class="tick" style="left:25%"></span><span class="tick" style="left:50%"></span>'
                f'<span class="tick" style="left:75%"></span>'
                f'<span class="tlab" style="left:0">0</span><span class="tlab" style="left:25%">1</span>'
                f'<span class="tlab" style="left:50%">2</span><span class="tlab" style="left:75%">3</span>'
                f'<span class="tlab" style="left:100%">4+ {unit}</span></div>'
                f'<div class="fnote">{note}</div></div>')

    frows = ""
    for m, cn, sub in (("ashare", "A 股", f'{db_data["klines_market"].get("ashare",{}).get("codes","—")} 只'),
                       ("hk", "港股", "01211 / 01810"), ("us", "美股", "NVDA"), ("crypto", "加密", "BTC / ETH")):
        f = freshness.get(m, {})
        note = _esc(f.get("note", "未取到"))
        frows += scale_row(cn, sub, f.get("lag"), note, unit="自然日" if m in ("us", "crypto") else "交易日")

    # NAV chart
    nlab, _ = nav_points(db_data["nav"])
    nav_html = ""
    if nlab:
        cum_cls = "ok" if not nlab["cum"].startswith("-") else "warn"
        nav_html = f'''
      <div class="panel">
        <h3>模拟盘净值 · paper_history {len(db_data["nav"])} 个交易日</h3>
        <div class="nav-flex">
          <div class="nav-stats">
            <div class="big">{nlab["last_v"]}</div>
            <div style="font-size:12px;color:var(--muted);margin-bottom:8px">最新 {nlab["last_d"]}</div>
            <div class="row"><span>区间峰值 {nlab["peak_d"]}</span><span>{nlab["peak_v"]}</span></div>
            <div class="row"><span>距峰值回撤</span><span>{nlab["dd"]}</span></div>
            <div class="row"><span>累计收益</span><span>{nlab["cum"]}</span></div>
            <div class="row"><span>周末行检查</span><span>{"无异常 ✓" if not db_data["ph_weekend"] else "存在周末行 ✗"}</span></div>
          </div>
          <svg viewBox="0 0 570 135" width="100%" style="min-width:340px;flex:1" role="img" aria-label="净值曲线">
            <line x1="10" y1="108" x2="550" y2="108" stroke="#d4d9dd" stroke-width="1" stroke-dasharray="3 3"/>
            <text x="10" y="122" font-family="IBM Plex Mono" font-size="9.5" fill="#66707a">起步 {nlab["cum"] and ""}{nav_range["first_d"]}</text>
            <polyline fill="none" stroke="#2b6d8f" stroke-width="2" stroke-linejoin="round" points="{nlab["polyline"]}"/>
            <circle cx="{nlab["peak"].split(",")[0]}" cy="{nlab["peak"].split(",")[1]}" r="3" fill="#2b6d8f"/>
            <circle cx="{nlab["last"].split(",")[0]}" cy="{nlab["last"].split(",")[1]}" r="3.5" fill="#2b6d8f" stroke="#ffffff" stroke-width="1.5"/>
            <text x="{float(nlab["peak"].split(",")[0])-8:.0f}" y="{float(nlab["peak"].split(",")[1])+2:.0f}" font-family="IBM Plex Mono" font-size="9.5" fill="#66707a" text-anchor="end">峰值 {nlab["peak_v"]} ({nlab["peak_d"][5:]})</text>
            <text x="{float(nlab["last"].split(",")[0])-2:.0f}" y="{float(nlab["last"].split(",")[1])-6:.0f}" font-family="IBM Plex Mono" font-size="9.5" fill="#66707a" text-anchor="end">{nlab["last_v"]} ({nlab["last_d"][5:]})</text>
            <text x="550" y="99" font-family="IBM Plex Mono" font-size="9.5" fill="#66707a" text-anchor="end">{nlab["last_d"]}</text>
          </svg>
        </div>
      </div>'''

    # calendar strip（当月）
    month_start = today.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    ndays = (next_month - month_start).days
    rev_set = set(reports["review_html"]["dates"])
    dai_set = set(reports["daily_html"]["dates"])
    wk_set = set(reports["weekly_html"]["dates"]) | set(reports["report_weekly_html"]["dates"])

    def cal_row(kind: str) -> str:
        cells = []
        for i in range(1, ndays + 1):
            d = month_start.replace(day=i)
            iso = d.isoformat()
            have = (iso in rev_set) if kind == "review" else (iso in dai_set)
            if kind == "weekly":
                if d.weekday() == 4:
                    cls = "wk" if iso in wk_set else "miss"
                else:
                    cls = "fut" if d > today else "dim"
            elif d > today:
                cls = "fut"
            elif have:
                cls = "have"
            elif not is_weekday(d):
                cls = "dim"
            else:
                cls = "miss"
            cells.append(f'<div class="cell {cls}">{i}</div>')
        return '<div class="cal">' + "".join(cells) + "</div>"

    rev_miss = sum(1 for i in range(1, ndays + 1)
                   if month_start.replace(day=i) <= today
                   and is_weekday(month_start.replace(day=i))
                   and month_start.replace(day=i).isoformat() not in rev_set)
    dai_miss = [month_start.replace(day=i).isoformat() for i in range(1, ndays + 1)
                if month_start.replace(day=i) <= today and is_weekday(month_start.replace(day=i))
                and month_start.replace(day=i).isoformat() not in dai_set]

    # coverage
    wtiles = ""
    for w in watchlist:
        code, name, mkt = w["code"], _esc(w["name"]), w["market"]
        kmax = db_data["code_max"].get(mkt, {}).get(code, "—")
        ann = db_data["ann"].get(code, {}).get("max")
        ann_html = f'<div class="ln"><span>公告 <b>{ann or "—"}</b></span><span class="seq-ic">静默</span></div>' \
            if ann and tier(ann, today) == "stale" else \
            (f'<div class="ln"><span>公告 <b>{ann}</b></span><span class="ok-ic">✓</span></div>' if ann else "")
        kmark = '<span class="ok-ic">✓</span>'
        if mkt == "us" and kmax != freshness.get("us", {}).get("_max"):
            kmark = '<span class="seq-ic">时序差</span>'
        wtiles += (f'<div class="wtile"><div class="code">{code}</div><div class="nm">{name}</div>'
                   f'<div class="ln"><span>K 线 <b>{kmax}</b></span>{kmark}</div>{ann_html}</div>')
    qtiles = ""
    for q in queue:
        code = q["code"] if isinstance(q, dict) else str(q)
        ann = db_data["ann"].get(code, {}).get("max")
        t = tier(ann, today)
        qtiles += f'<div class="qtile {t}"><div class="code">{code}</div><div class="d">{ann or "—"}</div></div>'
    stale_codes = [q["code"] for q in queue if isinstance(q, dict)
                   and tier(db_data["ann"].get(q["code"], {}).get("max"), today) == "stale"]

    # findings table
    lvl_tag = {"p1": '<span class="tag p1">P1</span>', "warn": '<span class="tag warn">观察</span>',
               "info": '<span class="tag dim">信息</span>'}
    frows_inc = "".join(
        f'<tr><td>{lvl_tag[f["level"]]}</td><td><b>{_esc(f["title"])}</b></td><td>{_esc(f["detail"])}</td></tr>'
        for f in findings) or '<tr><td><span class="tag ok">正常</span></td><td>规则扫描未发现异常</td><td>—</td></tr>'

    # tasks table tail
    trows = "".join(
        f'<tr><td class="mono">{_esc(t["name"])}</td><td>{_esc(t["state"])}</td>'
        f'<td class="mono">{_esc(t["last_run"])}</td><td class="mono">{t["result"]}</td>'
        f'<td class="mono">{_esc(t["next_run"])}</td></tr>'
        for t in tasks) or '<tr><td colspan="5">计划任务信息未取到</td></tr>'

    log_rows = "".join(
        f'<tr><td class="mono">{_esc(r["name"])}</td>'
        f'<td>{"缺失" if not r.get("exists") else _esc(r.get("mtime","—"))}</td>'
        f'<td>{r.get("err_count", 0)}</td><td class="mono">{_esc(r.get("last_done","—"))[:90]}</td></tr>'
        for r in logs)

    banner = ""
    if p1:
        det = "；".join(f'{f["title"]}（{f["detail"]}）' for f in p1)
        banner = f'<div class="banner"><b>P1</b><div><b>{_esc("；".join(f["title"] for f in p1))}</b><br>' \
                 f'<span style="color:var(--muted)">{_esc(det)}</span></div></div>'

    base_date = (baseline or {}).get("generated_at", "—")[:10] if baseline else "—"
    month_lbl = month_start.strftime("%Y-%m")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ashare-monitor 数据积累体检 {today.isoformat()}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#f4f5f6; --surface:#ffffff; --border:#e4e7ea; --border-soft:#eef0f2;
  --text:#171c21; --muted:#66707a;
  --accent:#2b6d8f; --accent-ink:#20556f; --accent-soft:#eaf2f6;
  --ok:#1a7f37; --ok-soft:#e9f4ec;
  --warn:#955600; --warn-soft:#fbf0d9;
  --danger:#c22731; --danger-soft:#fcebec;
  --track:#dfe3e7;
  --sans:"IBM Plex Sans","Microsoft YaHei",sans-serif;
  --mono:"IBM Plex Mono",Consolas,monospace;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{font-family:var(--sans);background:var(--bg);color:var(--text);line-height:1.55;font-size:14px}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 20px}}
header{{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.94);backdrop-filter:blur(6px);border-bottom:1px solid var(--border)}}
.hd{{display:flex;align-items:center;gap:16px;padding:12px 0;flex-wrap:wrap}}
.hd h1{{font-size:17px;font-weight:700;letter-spacing:-.01em}}
.hd .date{{font-family:var(--mono);font-size:13px;color:var(--muted)}}
.verdict{{display:inline-flex;align-items:center;gap:7px;padding:3px 12px;border-radius:99px;font-size:12.5px;font-weight:600}}
.verdict .dot{{width:8px;height:8px;border-radius:50%}}
.verdict.p1{{background:var(--danger-soft);color:var(--danger)}}
.verdict.p1 .dot{{background:var(--danger)}}
.verdict.ok{{background:var(--ok-soft);color:var(--ok)}}
.verdict.ok .dot{{background:var(--ok)}}
nav{{margin-left:auto;display:flex;gap:2px;flex-wrap:wrap}}
nav a{{font-size:12.5px;color:var(--muted);text-decoration:none;padding:4px 10px;border-radius:6px}}
nav a:hover{{background:var(--accent-soft);color:var(--accent-ink)}}
.banner{{display:flex;gap:12px;align-items:flex-start;background:var(--danger-soft);border:1px solid #f2cfd1;border-radius:10px;padding:13px 16px;margin:20px 0 6px;font-size:13.5px}}
.banner b{{color:var(--danger)}}
section{{margin-top:34px;scroll-margin-top:70px}}
.sec-head{{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}}
.sec-no{{font-family:var(--mono);font-size:12px;font-weight:600;color:var(--accent)}}
.sec-head h2{{font-size:16px;font-weight:700;letter-spacing:-.01em}}
.sec-head .hint{{font-size:12px;color:var(--muted)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}}
.kpi{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:13px 15px 11px}}
.kpi .name{{font-family:var(--mono);font-size:11.5px;color:var(--muted)}}
.kpi .num{{font-family:var(--mono);font-size:23px;font-weight:600;margin-top:3px;letter-spacing:-.02em}}
.kpi .delta{{display:inline-block;margin-top:5px;font-family:var(--mono);font-size:11.5px;padding:1px 7px;border-radius:5px}}
.kpi .delta.up{{background:var(--ok-soft);color:var(--ok)}}
.kpi .delta.flat{{background:var(--border-soft);color:var(--muted)}}
.panel{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin-top:10px}}
.panel>h3{{font-size:13px;font-weight:600;color:var(--muted);margin-bottom:10px}}
.frow{{display:grid;grid-template-columns:130px 1fr 330px;gap:14px;align-items:start;padding:10px 0;border-bottom:1px dashed var(--border-soft)}}
.frow:last-child{{border-bottom:none}}
.fname{{font-weight:600;font-size:13px;padding-top:1px}}
.fname small{{display:block;font-weight:400;font-family:var(--mono);font-size:11px;color:var(--muted)}}
.fscale{{position:relative;height:18px;background:var(--track);border-radius:5px;margin-bottom:16px}}
.fscale .fill{{position:absolute;left:0;top:0;height:100%;background:var(--accent);border-radius:5px;min-width:10px}}
.fscale .tick{{position:absolute;top:-4px;width:1px;height:26px;background:#c6ccd2}}
.fscale .tlab{{position:absolute;top:24px;font-family:var(--mono);font-size:10.5px;color:var(--muted);transform:translateX(-50%)}}
.fnote{{font-size:12px;color:var(--muted);padding-top:2px}}
.fnote b{{color:var(--text)}}
.nav-flex{{display:flex;gap:22px;align-items:flex-start;flex-wrap:wrap}}
.nav-stats{{min-width:170px}}
.nav-stats .big{{font-family:var(--mono);font-size:26px;font-weight:600}}
.nav-stats .row{{display:flex;justify-content:space-between;font-size:12.5px;padding:4px 0;border-bottom:1px dashed var(--border-soft)}}
.nav-stats .row span:last-child{{font-family:var(--mono)}}
.cal{{display:grid;grid-template-columns:repeat(auto-fit,minmax(24px,1fr));gap:3px;margin-top:6px}}
.cal .cell{{aspect-ratio:1;border-radius:4px;display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:10px;color:transparent}}
.cal .cell.have{{background:var(--ok-soft);outline:1px solid #bfe0c9}}
.cal .cell.miss{{background:var(--danger-soft);outline:1px solid #f0bfc2;color:var(--danger);font-weight:600}}
.cal .cell.dim{{background:var(--border-soft)}}
.cal .cell.fut{{background:transparent;outline:1px dashed #d4d9dd}}
.cal .cell.wk{{background:var(--accent);color:#fff;font-weight:600}}
.cal-legend{{display:flex;gap:16px;margin-top:10px;font-size:11.5px;color:var(--muted);flex-wrap:wrap}}
.cal-legend i{{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}}
.cal-row-label{{font-size:12.5px;font-weight:600;margin-top:14px;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}}
.cal-row-label small{{font-weight:400;color:var(--muted);font-family:var(--mono)}}
.cov-flex{{display:flex;gap:20px;flex-wrap:wrap}}
.cov-col{{flex:1;min-width:300px}}
.watch-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}}
.wtile{{border:1px solid var(--border);border-radius:8px;padding:9px 11px;background:var(--surface)}}
.wtile .code{{font-family:var(--mono);font-weight:600;font-size:13px}}
.wtile .nm{{font-size:11.5px;color:var(--muted);margin-bottom:4px}}
.wtile .ln{{font-size:11px;color:var(--muted);display:flex;justify-content:space-between}}
.wtile .ln b{{font-family:var(--mono);font-weight:500;color:var(--text)}}
.wtile .ok-ic{{color:var(--ok);font-family:var(--mono)}}
.wtile .seq-ic{{color:var(--warn);font-family:var(--mono)}}
.queue-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:6px}}
.qtile{{border:1px solid var(--border);border-radius:6px;padding:6px 8px;background:var(--surface)}}
.qtile .code{{font-family:var(--mono);font-size:11px;font-weight:600}}
.qtile .d{{font-family:var(--mono);font-size:10.5px;margin-top:1px}}
.qtile.fresh{{border-color:#a9c9db;background:var(--accent-soft)}}
.qtile.fresh .d{{color:var(--accent-ink)}}
.qtile.mid .d{{color:var(--muted)}}
.qtile.stale{{border-color:#ecd9a8;background:#fdf8ec}}
.qtile.stale .d{{color:var(--warn)}}
.tier-note{{margin-top:10px;font-size:12px;color:var(--muted)}}
.tier-note b{{color:var(--text)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f6f7f8;text-align:left;padding:7px 10px;font-weight:600;font-size:12.5px;color:#4a525a;border-bottom:1px solid var(--border)}}
td{{padding:8px 10px;border-bottom:1px solid var(--border-soft);vertical-align:top}}
tr:last-child td{{border-bottom:none}}
.mono{{font-family:var(--mono);font-size:12.5px}}
.tag{{display:inline-block;padding:1px 9px;border-radius:99px;font-size:11.5px;font-weight:600;white-space:nowrap}}
.tag.ok{{background:var(--ok-soft);color:var(--ok)}}
.tag.warn{{background:var(--warn-soft);color:var(--warn)}}
.tag.p1{{background:var(--danger-soft);color:var(--danger)}}
.tag.dim{{background:var(--border-soft);color:var(--muted)}}
footer{{margin-top:36px;padding:16px 0 30px;border-top:1px solid var(--border);color:var(--muted);font-size:12px;text-align:center}}
@media(max-width:760px){{
  .frow{{grid-template-columns:1fr;gap:6px}}
  .fscale{{max-width:420px}}
  .cal .cell{{font-size:8.5px;border-radius:3px}}
}}
</style>
</head>
<body>
<header><div class="wrap hd">
  <div><h1>ashare-monitor 数据积累体检</h1>
  <span class="date">{today.isoformat()} · 读数 {now.strftime("%m-%d %H:%M")}</span></div>
  <span class="verdict {verdict_cls}"><span class="dot"></span>{verdict_txt}</span>
  <nav><a href="#overview">概览</a><a href="#fresh">新鲜度</a><a href="#coverage">覆盖</a><a href="#reports">报告</a><a href="#ops">运维</a><a href="#incidents">异常与待办</a></nav>
</div></header>
<div class="wrap">
  {banner}

  <section id="overview">
    <div class="sec-head"><span class="sec-no">01</span><h2>总量概览</h2><span class="hint">对比基线 {base_date} · SQLite 只读实测</span></div>
    <div class="kpis">{kpis}</div>
    <div class="panel" style="padding:0;overflow:hidden"><table>
      <tr><th>市场</th><th>标的</th><th>K 线行数</th><th>历史区间</th><th>最新 date</th></tr>
      {mrows}
    </table></div>
  </section>

  <section id="fresh">
    <div class="sec-head"><span class="sec-no">02</span><h2>数据新鲜度</h2><span class="hint">中性刻度 · 红涨绿跌不适用 · 探针仅在落后 ≥1 交易日时触发</span></div>
    <div class="panel">{frows}</div>
    {nav_html}
  </section>

  <section id="coverage">
    <div class="sec-head"><span class="sec-no">03</span><h2>覆盖情况</h2><span class="hint">{len(watchlist)} 只自选 + {len(queue)} 只高股息队列</span></div>
    <div class="panel"><div class="cov-flex">
      <div class="cov-col">
        <h3 style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:10px">自选 {len(watchlist)} 只 — K 线与公告</h3>
        <div class="watch-grid">{wtiles}</div>
      </div>
      <div class="cov-col">
        <h3 style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:10px">高股息队列 {len(queue)} 只 — 按公告日期分层</h3>
        <div class="queue-grid">{qtiles}</div>
        <div class="tier-note"><b>{len(stale_codes)} 只滞后判定为源侧静默期</b>：<span class="mono" style="font-size:11.5px">{" / ".join(stale_codes) or "无"}</span></div>
      </div>
    </div></div>
  </section>

  <section id="reports">
    <div class="sec-head"><span class="sec-no">04</span><h2>日报 / 周报 / 月报积累</h2><span class="hint">{month_lbl} 日历轴 · 真实文件枚举</span></div>
    <div class="panel">
      <div class="cal-row-label">收盘复盘 review <small>每日 15:05 · output {reports["review_html"]["count"]} 份 + vault {reports["review_vault_md"]["count"]} 份</small>
        <span class="tag {"ok" if rev_miss == 0 else "warn"}">当月缺 {rev_miss} 天</span></div>
      {cal_row("review")}
      <div class="cal-row-label">period 日报 daily <small>仅工作日 19:00 · output {reports["daily_html"]["count"]} 份</small>
        <span class="tag {"ok" if not dai_miss else "p1"}">{"当月无缺档" if not dai_miss else "缺 " + " / ".join(d[5:] for d in dai_miss)}</span></div>
      {cal_row("daily")}
      <div class="cal-row-label">周五周报 weekly / report-weekly <small>{reports["weekly_html"]["count"]} + {reports["report_weekly_html"]["count"]} 份</small>
        <span class="tag {"ok" if not (extra or {}).get("miss_weekly") else "warn"}">{"周五连续 ✓" if not (extra or {}).get("miss_weekly") else "缺 " + " / ".join(d[5:] for d in (extra or {}).get("miss_weekly", []))}</span></div>
      {cal_row("weekly")}
      <div class="cal-legend">
        <span><i style="background:var(--ok-soft);outline:1px solid #bfe0c9"></i>已生成</span>
        <span><i style="background:var(--danger-soft);outline:1px solid #f0bfc2"></i>缺档</span>
        <span><i style="background:var(--border-soft)"></i>非生成日（周末）</span>
        <span><i style="background:var(--accent)"></i>周五（周报）</span>
        <span><i style="background:#fff;outline:1px dashed #d4d9dd"></i>未来</span>
      </div>
      <table style="margin-top:16px">
        <tr><th>类别</th><th>份数</th><th>最新</th></tr>
        <tr><td>review 复盘</td><td class="mono">{reports["review_html"]["count"]} + vault {reports["review_vault_md"]["count"]}</td><td class="mono">{reports["review_html"]["latest"] or "—"}</td></tr>
        <tr><td>daily 日报</td><td class="mono">{reports["daily_html"]["count"]}</td><td class="mono">{reports["daily_html"]["latest"] or "—"}</td></tr>
        <tr><td>weekly 周报</td><td class="mono">{reports["weekly_html"]["count"]}</td><td class="mono">{reports["weekly_html"]["latest"] or "—"}</td></tr>
        <tr><td>report-weekly</td><td class="mono">{reports["report_weekly_html"]["count"]}</td><td class="mono">{reports["report_weekly_html"]["latest"] or "—"}</td></tr>
        <tr><td>monthly 月报</td><td class="mono">{reports["monthly_html"]["count"]}</td><td class="mono">{reports["monthly_html"]["latest"] or "—"}</td></tr>
      </table>
    </div>
  </section>

  <section id="ops">
    <div class="sec-head"><span class="sec-no">05</span><h2>计划任务 / 备份 / 日志 / 双仓</h2><span class="hint">Get-ScheduledTask 实测 · 267011=从未运行可忽略</span></div>
    <div class="panel" style="padding:0;overflow:hidden"><table>
      <tr><th>任务</th><th>状态</th><th>上次运行</th><th>result</th><th>下次运行</th></tr>
      {trows}
    </table></div>
    <div class="panel" style="padding:0;overflow:hidden"><table>
      <tr><th>日志</th><th>更新时间</th><th>疑似错误行</th><th>最近完成标记</th></tr>
      {log_rows}
    </table></div>
    <div class="panel"><table>
      <tr><th>项</th><th>状态</th></tr>
      <tr><td>数据库备份</td><td>{backups["count"]} 份 · 最新 <span class="mono">{_esc(backups["latest"] or "—")}</span>（{_esc(backups["latest_mtime"] or "—")}）</td></tr>
      <tr><td>投研仓 invest</td><td class="mono">{_esc(repos.get("invest",{}).get("head","—"))} vs origin {_esc(repos.get("invest",{}).get("remote","—"))}{" · 工作树有改动" if repos.get("invest",{}).get("dirty") else " · 干净"}</td></tr>
      <tr><td>笔记仓 notes</td><td class="mono">{_esc(repos.get("notes",{}).get("head","—"))} vs origin {_esc(repos.get("notes",{}).get("remote","—"))}{" · 工作树有改动" if repos.get("notes",{}).get("dirty") else " · 干净"}</td></tr>
    </table></div>
  </section>

  <section id="incidents">
    <div class="sec-head"><span class="sec-no">06</span><h2>异常与待办</h2><span class="hint">规则自动扫描 · 「未记录…疑似休市」属护栏预期不计入</span></div>
    <div class="panel" style="padding:0;overflow:hidden"><table>
      <tr><th style="width:90px">级别</th><th style="width:300px">事项</th><th>细节</th></tr>
      {frows_inc}
    </table></div>
  </section>

  <footer>ashare-monitor scripts/health_report.py · 生成 {now.strftime("%Y-%m-%d %H:%M")} · 数字均来自 SQLite / 文件系统 / 计划任务 API 真实查询</footer>
</div>
</body>
</html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="ashare-monitor 数据积累体检报告生成器")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    ap.add_argument("--out", default=None, help="输出 HTML 路径（默认 output/health-YYYY-MM-DD.html）")
    ap.add_argument("--no-snapshot", action="store_true", help="试跑：不写回基线快照")
    ap.add_argument("--notes", default=None, help="AI 判定 JSON（incidents/observations 追加进快照）")
    args = ap.parse_args()

    now = datetime.now()
    today = now.date()
    db_path = Path(args.db)

    db_data = collect_db(db_path)
    reports = collect_reports()
    backups = collect_backups()
    logs = collect_logs()
    watchlist = parse_watchlist()
    queue = parse_queue()
    with tempfile.TemporaryDirectory() as td:
        tasks = collect_tasks(Path(td))
    repos = collect_repos()

    analysis = analyze(db_data, reports, tasks, backups, repos, logs, today, now)

    baseline = None
    snap_path = Path(args.snapshot)
    if snap_path.is_file():
        try:
            baseline = json.loads(snap_path.read_text(encoding="utf-8"))
        except ValueError:
            baseline = None

    nav_last = {"date": db_data["nav"][-1][0], "nav": db_data["nav"][-1][1]} if db_data["nav"] else {}
    queue_codes = [q["code"] for q in queue if isinstance(q, dict)]
    coverage = {
        "watchlist": len(watchlist),
        "dividend_queue": len(queue_codes),
        "queue_klines": f'{sum(1 for c in queue_codes if c in db_data["code_max"]["ashare"])}/{len(queue_codes)}',
        "queue_announcements": f'{sum(1 for c in queue_codes if c in db_data["ann"])}/{len(queue_codes)}',
        "queue_research_reports": f'{sum(1 for c in queue_codes if c in db_data["research"])}/{len(queue_codes)}',
        "queue_financials": f'{sum(1 for c in queue_codes if c in db_data["fin"])}/{len(queue_codes)}',
    }

    notes = None
    if args.notes:
        notes = json.loads(Path(args.notes).read_text(encoding="utf-8"))

    out_path = Path(args.out) if args.out else DEFAULT_OUTDIR / f"health-{today.isoformat()}.html"
    render(out_path, db_data, reports, analysis["freshness"], analysis["findings"],
           backups, tasks, logs, repos, watchlist, queue, today, now, baseline,
           nav_points(db_data["nav"])[1], analysis.get("extra"))

    if not args.no_snapshot:
        write_snapshot(snap_path, db_data, reports, analysis["freshness"], coverage,
                       backups, repos, nav_last, notes, now)

    print(f"OK report -> {out_path}")
    print(f"OK snapshot {'skipped (--no-snapshot)' if args.no_snapshot else '-> ' + str(snap_path)}")
    p1 = [f for f in analysis["findings"] if f["level"] == "p1"]
    print(f"P1 findings: {len(p1)}")
    for f in analysis["findings"]:
        print(f"  [{f['level']}] {f['title']} | {f['detail'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
