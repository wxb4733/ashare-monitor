# -*- coding: utf-8 -*-
"""全量 K 线增量更新（每日任务用）。

覆盖范围 = 库内所有已跟踪的 ashare / hk 标的（自选股 + 高股息扩容队列），
按库内最新日期向前补 N 天，幂等可重复跑。

背景（2026-10-16）：daily_backfill_task.bat 原先只对 config.yaml watchlist
跑 backfill_kline，高股息队列 34 只自 10-10 一次性回填后再未更新，导致体检
时 A 股大面积停在 2026-10-09（落后 4 个交易日）。本脚本补齐该覆盖缺口。

用法：python scripts/backfill_kline_all.py [--days 20] [--market ashare,hk]
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ashare_monitor.backfill import backfill_kline_incremental  # noqa: E402

DB = r"E:\database\sqlite\ashare_monitor.db"


def tracked_codes(markets: tuple[str, ...]) -> list[tuple[str, str]]:
    """库内已跟踪标的（按库内最新日期升序，落后的优先补）。"""
    conn = sqlite3.connect(DB)
    try:
        q = (f"SELECT market, code, MAX(date) FROM klines "
             f"WHERE market IN ({','.join('?' * len(markets))}) "
             f"GROUP BY market, code ORDER BY MAX(date)")
        return [(code, market) for market, code, _ in
                conn.execute(q, markets).fetchall()]
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="全量 K 线增量更新（自选 + 队列）")
    ap.add_argument("--days", type=int, default=20, help="回看天数（默认 20）")
    ap.add_argument("--market", default="ashare,hk", help="市场，逗号分隔")
    args = ap.parse_args()

    markets = tuple(m.strip() for m in args.market.split(",") if m.strip())
    codes = tracked_codes(markets)
    print(f"K 线增量：{len(codes)} 只（{','.join(markets)}），回看 {args.days} 天")

    result = backfill_kline_incremental(codes, days=args.days)
    added = sum(v[0] for v in result.values())
    failed = [c for c, (new, total) in result.items() if total == 0]
    for code, (new, total) in result.items():
        print(f"  {code}: +{new}（库内 {total}）")
    print(f"合计新增 {added} 根；失败/空 {len(failed)} 只"
          + (f"：{','.join(failed)}" if failed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
