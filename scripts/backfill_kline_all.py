# -*- coding: utf-8 -*-
"""全量 K 线增量更新（每日任务用）。

覆盖范围 = 库内所有已跟踪的 ashare / hk 标的（自选股 + 高股息扩容队列）
**并上模拟盘当前持仓**，按库内最新日期向前补 N 天，幂等可重复跑。

背景（2026-10-16）：daily_backfill_task.bat 原先只对 config.yaml watchlist
跑 backfill_kline，高股息队列 34 只自 10-10 一次性回填后再未更新，导致体检
时 A 股大面积停在 2026-10-09（落后 4 个交易日）。本脚本补齐该覆盖缺口。

背景（2026-11-03）：universe 原先只从 klines 表反查，**零行的标的自举失败**——
11-01 调仓买入 10 只高股息股（000915/002572/002763/600219/600866/600983/
601717/603165/603167/603551）在库内 0 根 K 线，永远进不了回填范围，导致无法
离线估值、无法 `strategy track --date` 补录、复盘缺图。现改为 klines ∪ 持仓。

用法：python scripts/backfill_kline_all.py [--days 20] [--market ashare,hk]
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ashare_monitor.backfill import backfill_kline_incremental  # noqa: E402

DB = r"E:\database\sqlite\ashare_monitor.db"


def infer_market(code: str) -> str:
    """按代码形态推断市场：5 位数字=港股，其余按 A 股。"""
    code = (code or "").strip()
    if code.isdigit() and len(code) == 5:
        return "hk"
    return "ashare"


def merge_universe(klines_rows: list[tuple[str, str]],
                   position_codes: list[str],
                   markets: tuple[str, ...]) -> list[tuple[str, str]]:
    """库内已跟踪标的 ∪ 模拟盘持仓（去重，持仓新标的排前面）。

    :param klines_rows: [(market, code), ...]，来自 klines 表反查
    :param position_codes: paper_positions 里的代码
    """
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for code in position_codes:
        market = infer_market(code)
        key = (market, code)
        if market in markets and key not in seen:
            seen.add(key)
            out.append(key)
    for market, code in klines_rows:
        key = (market, code)
        if market in markets and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def tracked_codes(markets: tuple[str, ...]) -> list[tuple[str, str]]:
    """库内已跟踪标的 + 模拟盘持仓（落后/无数据的优先补）。"""
    conn = sqlite3.connect(DB)
    try:
        q = (f"SELECT market, code, MAX(date) FROM klines "
             f"WHERE market IN ({','.join('?' * len(markets))}) "
             f"GROUP BY market, code ORDER BY MAX(date)")
        rows = [(market, code) for market, code, _ in
                conn.execute(q, markets).fetchall()]
        positions = [r[0] for r in
                     conn.execute("SELECT code FROM paper_positions").fetchall()]
    finally:
        conn.close()
    merged = merge_universe(rows, positions, markets)
    return [(code, market) for market, code in merged]


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
