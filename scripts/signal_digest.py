"""高胜率信号日报：今日触发信号 × verify 历史命中率 → 只推可执行的信号。

思路（挣钱导向的信号消费闭环）：
    1. 对每只自选股（A/H/US，crypto 跳过）扫描 5 类规则信号，看最后一根 K 线是否触发；
    2. 对触发的规则查 verify 历史命中率（默认回看 500 日、前瞻 5 交易日）；
    3. 只把「胜率 >= 阈值 且 样本 >= 阈值」的信号列为可执行，其余归入观察区；
    4. 叠加 radar 多空雷达总分做背景；
    5. 产出 markdown 报告；若设置 ASHARE_MONITOR_WEBHOOK 同时推送
       （企业微信/钉钉 text 格式，自动截断到安全长度）。

用法（必须在仓库根目录运行，DB_PATH 是相对路径）:
    .venv/Scripts/ashare-monitor.exe 所在 venv:
    .venv/Scripts/python.exe scripts/signal_digest.py [--forward 5] [--days 500]
        [--min-win 55] [--min-signals 15]

声明：规则化统计信号，不构成投资建议。过往命中率不预示未来表现。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
os.chdir(REPO)  # DB_PATH = data/ashare_monitor.db 相对仓库根

from ashare_monitor.config import load_config            # noqa: E402
from ashare_monitor.notify import WebhookNotifier        # noqa: E402
from ashare_monitor.radar import score_stock             # noqa: E402
from ashare_monitor.storage import load_klines           # noqa: E402
from ashare_monitor.verify import RULES, scan_signals, verify_all  # noqa: E402


def triggered_rules(rows: list[dict]) -> list[str]:
    """返回在最后一根 K 线上触发的规则名列表。"""
    hit = []
    for rule in RULES:
        try:
            idxs = scan_signals(rows, rule)
        except Exception:  # noqa: BLE001
            continue
        if idxs and idxs[-1] == len(rows) - 1:
            hit.append(rule)
    return hit


def build_digest(min_win: float, min_signals: int, forward: int,
                 days: int) -> tuple[str, str]:
    """返回 (markdown, 推送纯文本)。"""
    cfg = load_config()
    as_of = datetime.now().strftime("%Y-%m-%d")
    exec_rows, watch_rows, radar_lines = [], [], []

    for it in cfg.watchlist:
        code, name = str(it["code"]), str(it.get("name", it["code"]))
        market = str(it.get("market", "ashare"))
        if market == "crypto":
            continue
        try:
            rows = load_klines(code, market)
        except Exception:  # noqa: BLE001
            rows = []
        if len(rows) < 60:
            continue

        # 多空雷达背景
        try:
            r = score_stock(code, name, market, cfg=cfg)
            radar_lines.append(f"- {name}({code}): 总分 {r.total:+.1f} → {r.verdict}")
        except Exception:  # noqa: BLE001
            pass

        hit_rules = triggered_rules(rows)
        if not hit_rules:
            continue
        stats = {s["rule"]: s for s in verify_all(rows[-days:], forward=forward)}
        for rule in hit_rules:
            s = stats.get(rule)
            if not s or s["win_rate"] is None:
                continue
            row = {
                "code": code, "name": name, "rule": rule,
                "label": s["label"], "direction": s["direction"],
                "win": s["win_rate"], "n": s["signals"],
                "avg": s["avg_return"], "worst": s["worst"],
            }
            if s["win_rate"] >= min_win and s["signals"] >= min_signals:
                exec_rows.append(row)
            else:
                watch_rows.append(row)

    lines = [f"# 高胜率信号日报 {as_of}", ""]
    if exec_rows:
        lines += ["## ✅ 可执行信号（胜率≥%s%% 且样本≥%d）" % (min_win, min_signals), "",
                  "| 标的 | 信号 | 方向 | 胜率 | 样本 | 前瞻均值 | 最差 |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for r in exec_rows:
            act = "买入参考" if r["direction"] == "up" else "回避/止损参考"
            lines.append(
                f"| {r['name']}({r['code']}) | {r['label']} | {act} "
                f"| {r['win']}% | {r['n']} | {r['avg']:+.2f}% | {r['worst']:+.2f}% |")
    else:
        lines += ["## ✅ 可执行信号", "", "今日无满足胜率阈值的信号。"]
    if watch_rows:
        lines += ["", "## 👀 观察区（胜率或样本不足，仅记录不操作）", "",
                  "| 标的 | 信号 | 胜率 | 样本 | 前瞻均值 |",
                  "| --- | --- | --- | --- | --- |"]
        for r in watch_rows:
            lines.append(
                f"| {r['name']}({r['code']}) | {r['label']} "
                f"| {r['win']}% | {r['n']} | {r['avg']:+.2f}% |")
    if radar_lines:
        lines += ["", "## 📡 多空雷达", *radar_lines]
    lines += ["", "---",
              "规则化统计信号，过往命中率不预示未来表现，不构成投资建议。"]

    md = "\n".join(lines)
    # 推送文本：企业微信 text 上限 2048 字节，留余量截断
    text = md.replace("# ", "").replace("## ", "■ ").replace("|", " ").replace("---", "")
    text = "\n".join(l for l in text.splitlines() if l.strip())
    if len(text.encode("utf-8")) > 1800:
        text = text.encode("utf-8")[:1800].decode("utf-8", "ignore") + "\n…（详见 output 报告）"
    return md, text


def main() -> None:
    ap = argparse.ArgumentParser(description="高胜率信号日报")
    ap.add_argument("--forward", type=int, default=5)
    ap.add_argument("--days", type=int, default=500)
    ap.add_argument("--min-win", type=float, default=55.0)
    ap.add_argument("--min-signals", type=int, default=15)
    args = ap.parse_args()

    md, text = build_digest(args.min_win, args.min_signals,
                            args.forward, args.days)
    out = REPO / "output" / f"signal-digest-{datetime.now():%Y-%m-%d}.md"
    out.write_text(md, encoding="utf-8")
    print(f"[signal-digest] 报告已写入 {out}")

    webhook = os.environ.get("ASHARE_MONITOR_WEBHOOK")
    if webhook:
        try:
            WebhookNotifier(webhook).send_text(text)
            print("[signal-digest] 已推送 webhook")
        except Exception as exc:  # noqa: BLE001
            print(f"[signal-digest] webhook 推送失败: {exc}")


if __name__ == "__main__":
    main()
