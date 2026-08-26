"""高股息队列 34 家 K 线批量回填（腾讯源分段拉全量）。

数据源：web.ifzq.gtimg.cn fqkline（前复权日 K，多窗口推进）
落库：storage.record_klines（幂等，重复日期自动跳过，可断点续跑）
用法：python scripts/backfill_queue_kline.py [--top N] [--start YYYY-MM-DD]
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ashare_monitor import backfill  # noqa: E402
from ashare_monitor.storage import count_klines, record_klines  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _fetch_with_fallback(code: str, market: str, start: str) -> list:
    """腾讯分段拉全量；被限流（IP 级 501）时切新浪 1023 根兜底。"""
    from ashare_monitor import backfill

    try:
        return backfill._backfill_kline_tencent(code, market, start)
    except Exception as exc:  # noqa: BLE001
        print(f"    ↳ 腾讯受限，切新浪兜底: {exc}")
        return backfill._backfill_kline_sina(code, market, start)


def _fetch_sina_only(code: str, market: str, start: str) -> list:
    """强制新浪源（腾讯 IP 封禁未解时直连，近 4 年 1023 根）。"""
    from ashare_monitor import backfill

    return backfill._backfill_kline_sina(code, market, start)


def run_one(code: str, name: str, start: str,
            fetcher=None, recorder=None, counter=None,
            replace: bool = False) -> str:
    """单只回填：已有 K 线则跳过；否则腾讯拉取 + 落库。返回状态描述。

    :param replace: 先清空该 code 旧 K 线再拉（防新浪/腾讯前复权口径混源）
    """
    from ashare_monitor import backfill
    from ashare_monitor.storage import count_klines, record_klines

    fetcher = fetcher or _fetch_with_fallback
    recorder = recorder or record_klines
    counter = counter or count_klines

    before = counter(code, "ashare")
    if before > 0 and not replace:
        return f"已有 {before} 根，跳过"
    if replace and before > 0:
        from ashare_monitor.storage import get_conn

        conn = get_conn()
        try:
            conn.execute(
                "DELETE FROM klines WHERE market='ashare' AND code=?",
                (code[-6:] if code.isdigit() else code,))
            conn.commit()
        finally:
            conn.close()
        print(f"    ↳ 清空旧 {before} 根（--replace）")
    rows = fetcher(code, "ashare", start)
    new = recorder(rows, "ashare", code)
    total = counter(code, "ashare")
    return f"+{new} 根 (共 {total})"


def main() -> int:
    ap = argparse.ArgumentParser(description="高股息队列 K 线回填（腾讯源）")
    ap.add_argument("--top", type=int, default=0, help="仅回填前 N 家（0=全部）")
    ap.add_argument("--start", default="1990-01-01", help="起点日期（默认 1990-01-01）")
    ap.add_argument("--codes", default="", help="仅回填指定代码（逗号分隔，如 601939,601288）")
    ap.add_argument("--source", choices=("auto", "sina"), default="auto",
                    help="数据源：auto=腾讯→新浪兜底；sina=强制新浪（腾讯封禁时用）")
    ap.add_argument("--replace", action="store_true",
                    help="先清空该 code 旧 K 线再拉（防复权口径混源；限流解除后补全量用）")
    args = ap.parse_args()

    fetcher = _fetch_sina_only if args.source == "sina" else _fetch_with_fallback

    qf = ROOT / "output" / "backfill_queue.json"
    if not qf.exists():
        print(f"❌ 未找到队列 {qf}，先运行 gen_queue_westock.py")
        return 1
    queue = json.loads(qf.read_text(encoding="utf-8"))
    if args.codes:
        wanted = {c.strip() for c in args.codes.split(",") if c.strip()}
        queue = [it for it in queue if str(it["code"]) in wanted]
        print(f"== 定向补跑 {len(queue)} 家：{args.codes} ==")
    else:
        queue = queue[: args.top] if args.top else queue
        print(f"== 队列 {len(queue)} 家（起点 {args.start}）==")

    ok, fail, skipped = 0, [], 0
    for i, it in enumerate(queue, 1):
        code, name = str(it["code"]), it["name"]
        try:
            t0 = time.time()
            msg = run_one(code, name, args.start, fetcher=fetcher,
                          replace=args.replace)
            tag = "⏭" if "跳过" in msg else "✅"
            print(f"[{i:>2}/{len(queue)}] {tag} {name}({code}) {msg} "
                  f"({time.time()-t0:.0f}s)")
            if "跳过" in msg:
                skipped += 1
            else:
                ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[{i:>2}/{len(queue)}] ❌ {name}({code}) 失败: {exc}")
            fail.append((code, name, str(exc)[:80]))
        time.sleep(1.2)  # 节流，防腾讯限流

    print(f"\n== 完成：成功 {ok} / 跳过 {skipped} / 失败 {len(fail)} ==")
    for c, n, e in fail:
        print(f"  ❌ {n}({c}): {e}")
    return 0 if not fail else 2


if __name__ == "__main__":
    raise SystemExit(main())
