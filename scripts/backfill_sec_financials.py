"""SEC EDGAR 财报落库（经 OpenBB sec provider，免 key）——美股基本面权威源。

用法:
    单标的:  python scripts/backfill_sec_financials.py --code NVDA --name NVIDIA
    批量:    python scripts/backfill_sec_financials.py --codes "NVDA MSFT AAPL TSLA"
    重刷:    python scripts/backfill_sec_financials.py --codes "..." --force
             （默认幂等：已有 >= periods 期的标的自动跳过；--force 强制重拉）
    批量+延迟: python scripts/backfill_sec_financials.py --codes "..." --sleep 2

说明:
- 金额列单位 = 报告货币"亿"：美国本土公司 USD 亿美元；SEC 20-F 外国发行人
  （如 TSM/ASML）按本币列报，OpenBB 不做折算——currency 写真实报告货币
  （TWD/EUR），原值入库不换算（见 _REPORT_CURRENCY，诚实标注口径）
- ROE 采用恒等式 权益=总资产−总负债（避开 SEC common_equity 面值陷阱）
- ocf_per_share 置 NULL（SEC 三表无加权股数，不估算）
- 需先安装可选依赖: pip install -e ".[openbb]"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ashare_monitor.sec_financials import fetch_sec_financials  # noqa: E402
from ashare_monitor.storage import load_financials, record_financials  # noqa: E402

# 常见代码→名称映射（缺失时 name 留空，不影响数据）
_NAMES = {
    "NVDA": "NVIDIA", "MSFT": "Microsoft", "AAPL": "Apple", "GOOGL": "Alphabet",
    "GOOG": "Alphabet", "AMZN": "Amazon", "META": "Meta", "TSLA": "Tesla",
    "AVGO": "Broadcom", "AMD": "AMD", "TSM": "TSMC(ADR)", "MU": "Micron",
    "ASML": "ASML", "INTC": "Intel", "QCOM": "Qualcomm", "ORCL": "Oracle",
    "CRM": "Salesforce", "NFLX": "Netflix", "PLTR": "Palantir", "COST": "Costco",
    "UNH": "UnitedHealth", "JPM": "JPMorgan", "BRK.B": "Berkshire", "LLY": "EliLilly",
}

# 非 USD 报告货币（SEC 20-F 外国发行人按本币列报，OpenBB sec provider 不做折算；
# 落库 currency 写报告货币原值，金额单位=该币种"亿"，不做汇率换算——诚实标注）
_REPORT_CURRENCY = {
    "TSM": "TWD",   # 台积电 20-F：新台币（2.89 万亿 TWD ≈ 真实营收）
    "ASML": "EUR",  # ASML 20-F：欧元（282.6 亿 EUR ≈ 真实营收）
    # 待补：BABA/PDD/NIO 等中概（CNY）、TM/NSANY（JPY）、SHEL/BP（USD）…
}


def _run_one(code: str, name: str, periods: int, db: str,
             force: bool = False) -> dict:
    """单标的落库，返回结果摘要（失败不抛，返回 error）。

    幂等：库内已存在 >= periods 期时跳过（除非 force=True 强制重拉，重拉
    由 record_financials 的 code+report_date 唯一键去重，无脏数据）。
    """
    existing = len(load_financials(code, db_path=db))
    if not force and existing >= periods:
        return {"code": code, "status": "skip", "detail": f"已有 {existing} 期（>= {periods}）"}
    print(f"[..] {code} ({name or '?'}) 拉取 SEC 财报 periods={periods} …", flush=True)
    try:
        items = fetch_sec_financials(code, periods=periods)
    except Exception as exc:  # noqa: BLE001
        return {"code": code, "status": "error", "detail": f"{type(exc).__name__}: {exc}"}
    if not items:
        return {"code": code, "status": "error", "detail": "无数据返回"}
    currency = _REPORT_CURRENCY.get(code, "USD")
    if currency != "USD":
        print(f"  [注] {code} 为 SEC 20-F 外国发行人，报告货币 {currency}，"
              f"金额=该币种亿原值（未折算 USD）", flush=True)
    new, exist = record_financials(
        items, code, name=name, db_path=db, currency=currency,
    )
    total = len(load_financials(code, db_path=db))
    p = items[0]
    unit = {"TWD": "亿新台币", "EUR": "亿欧元", "CNY": "亿元"}.get(currency, "亿美元")
    detail = (f"FY {p.report_date}: 营收 {p.revenue} {unit}, 净利 {p.net_profit}, "
              f"毛利率 {p.gross_margin}%, ROE {p.roe}%, eps ${p.eps}")
    print(f"[ok] {code}: 新增 {new} / 已存在 {exist} / 库内共 {total} 期 | {detail}", flush=True)
    return {"code": code, "status": "ok", "detail": f"新增 {new} 期, 共 {total} 期"}


def main() -> int:
    ap = argparse.ArgumentParser(description="SEC EDGAR 财报落库（OpenBB sec provider）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--code", help="美股代码，如 NVDA")
    g.add_argument("--codes", help="批量：空格分隔代码列表，如 'NVDA MSFT AAPL'")
    ap.add_argument("--name", default="", help="单标的名称（--code 模式用）")
    ap.add_argument("--periods", type=int, default=5, help="落库财年数（默认 5）")
    ap.add_argument("--sleep", type=float, default=0.0, help="批量模式每标的时间隔秒（防 SEC 限流）")
    ap.add_argument("--force", action="store_true", help="强制重拉（默认幂等跳过已满标的）")
    ap.add_argument("--db", default=None, help="数据库路径（默认 data/ashare_monitor.db）")
    args = ap.parse_args()

    db = args.db or str(Path(__file__).resolve().parent.parent / "data" / "ashare_monitor.db")
    codes = [args.code] if args.code else args.codes.split()

    results = []
    for i, code in enumerate(codes):
        code = code.strip()
        if not code:
            continue
        name = _NAMES.get(code, args.name if args.code else "")
        results.append(_run_one(code, name, args.periods, db, force=args.force))
        if args.sleep and i < len(codes) - 1:
            time.sleep(args.sleep)

    ok = [r for r in results if r["status"] == "ok"]
    err = [r for r in results if r["status"] == "error"]
    skip = [r for r in results if r["status"] == "skip"]
    print("\n===== 汇总 =====")
    print(f"成功 {len(ok)} / 失败 {len(err)} / 跳过 {len(skip)}（共 {len(results)}）")
    for r in err:
        print(f"  ✗ {r['code']}: {r['detail']}")
    for r in ok[:8]:
        print(f"  ✓ {r['code']}: {r['detail']}")
    if len(ok) > 8:
        print(f"  … 其余 {len(ok) - 8} 家略")
    return 1 if err else 0


if __name__ == "__main__":
    raise SystemExit(main())
