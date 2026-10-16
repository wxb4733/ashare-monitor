# -*- coding: utf-8 -*-
"""高股息扩容队列：公告 / 研报 / 财报 批量回灌（东财源，幂等可续跑）。

背景（2026-10-16 体检）：队列 36 只只做过 K 线回填，公告/研报/财报覆盖 0/36。

用法：
    python scripts/backfill_queue_data.py                 # 全部 36 只，研报近 5 年
    python scripts/backfill_queue_data.py --years 10      # 研报近 10 年
    python scripts/backfill_queue_data.py --codes 600066,000651
    python scripts/backfill_queue_data.py --no-financial   # 只回灌公告+研报
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8")

QUEUE = ROOT / "output" / "backfill_queue.json"


def load_queue() -> list[dict]:
    return json.loads(QUEUE.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="高股息队列公告/研报/财报回灌")
    ap.add_argument("--years", type=int, default=5, help="研报回看年数（默认 5）")
    ap.add_argument("--codes", default="", help="仅指定代码（逗号分隔）")
    ap.add_argument("--no-news", action="store_true", help="跳过公告/研报")
    ap.add_argument("--no-financial", action="store_true", help="跳过财报")
    ap.add_argument("--sleep", type=float, default=0.4, help="每只间隔秒数（默认 0.4）")
    args = ap.parse_args()

    from ashare_monitor.backfill import backfill_financial, backfill_news

    queue = load_queue()
    if args.codes:
        want = {c.strip() for c in args.codes.split(",") if c.strip()}
        queue = [q for q in queue if q["code"] in want]

    print(f"队列数据回灌：{len(queue)} 只（研报近 {args.years} 年）")
    ok = fail = 0
    for i, item in enumerate(queue, 1):
        code, name = item["code"], item.get("name", "")
        res = {}
        try:
            if not args.no_news:
                res["news"] = backfill_news(code, years=args.years,
                                            market="ashare")
            if not args.no_financial:
                new, total = backfill_financial(code, "ashare")
                res["fin"] = {"new": new, "total": total}
            ok += 1
            n = (res.get("news") or {}).get("announcements", 0)
            r = (res.get("news") or {}).get("reports", 0)
            f = (res.get("fin") or {}).get("new", 0)
            print(f"[{i}/{len(queue)}] ✅ {name}({code}) "
                  f"公告+{n} 研报+{r} 财报+{f}", flush=True)
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"[{i}/{len(queue)}] ❌ {name}({code}) {str(exc)[:120]}",
                  flush=True)
        time.sleep(args.sleep)

    print(f"\n== 完成：成功 {ok} / 失败 {fail} ==")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
