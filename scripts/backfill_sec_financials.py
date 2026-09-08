"""SEC EDGAR 财报落库（经 OpenBB sec provider，免 key）——美股基本面权威源。

用法:
    python scripts/backfill_sec_financials.py --code NVDA --name NVIDIA
    python scripts/backfill_sec_financials.py --code NVDA --periods 8

说明:
- 金额列以 USD 亿美元落库（financials.currency='USD'；A 股 'CNY' 亿元口径由列标注区分）
- ROE 采用恒等式 权益=总资产−总负债（避开 SEC common_equity 面值陷阱）
- ocf_per_share 置 NULL（SEC 三表无加权股数，不估算）
- 需先安装可选依赖: pip install -e ".[openbb]"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ashare_monitor.sec_financials import fetch_sec_financials  # noqa: E402
from ashare_monitor.storage import load_financials, record_financials  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="SEC EDGAR 财报落库（OpenBB sec provider）")
    ap.add_argument("--code", required=True, help="美股代码，如 NVDA")
    ap.add_argument("--name", default="", help="名称（用于展示），默认留空")
    ap.add_argument("--periods", type=int, default=5, help="落库财年数（默认 5）")
    ap.add_argument("--db", default=None, help="数据库路径（默认 data/ashare_monitor.db）")
    args = ap.parse_args()

    db = args.db or str(Path(__file__).resolve().parent.parent / "data" / "ashare_monitor.db")
    print(f"[..] 拉取 SEC 财报: {args.code} (periods={args.periods}) …")
    items = fetch_sec_financials(args.code, periods=args.periods)
    if not items:
        print("无数据返回"); return 1
    new, exist = record_financials(
        items, args.code, name=args.name, db_path=db, currency="USD",
    )
    total = len(load_financials(args.code, db_path=db))
    print(f"[ok] 入库: 新增 {new} / 已存在 {exist} / 库内共 {total} 期")
    for p in items[:3]:
        print(f"     FY {p.report_date}: 营收 {p.revenue} 亿美元, 净利 {p.net_profit}, "
              f"毛利率 {p.gross_margin}%, ROE {p.roe}%, eps ${p.eps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
