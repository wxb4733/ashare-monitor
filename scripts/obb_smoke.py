"""OpenBB 集成冒烟测试：框架加载 + 免费数据源（yfinance）可达性探测。

用法:
    python scripts/obb_smoke.py            # 全量探测
    python scripts/obb_smoke.py --quick    # 仅框架加载（离线自检）

输出: output/obb_smoke_report.json（结构化报告，供复盘/文档引用）
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "output"
PER_CALL_TIMEOUT = 90  # 秒，yfinance 跨境慢


def probe_framework() -> dict:
    """阶段 1：框架加载自检（不触网）。"""
    import importlib.metadata
    from openbb import obb

    ver = importlib.metadata.version("openbb")
    # 统计命令树规模（equity / crypto / economy 子路由下叶子命令数）
    def count_leaves(node, depth: int = 0) -> int:
        if depth >= 4 or node is None:
            return 1 if callable(node) else 0
        attrs = [a for a in dir(node) if not a.startswith("_")]
        if not attrs:
            return 1 if callable(node) else 0
        return sum(count_leaves(getattr(node, a), depth + 1) for a in attrs)

    return {
        "openbb_version": ver,
        "import_ok": True,
        "equity_cmd_count": count_leaves(getattr(obb, "equity", None)),
        "crypto_cmd_count": count_leaves(getattr(obb, "crypto", None)),
        "economy_cmd_count": count_leaves(getattr(obb, "economy", None)),
    }


def probe_equity_hist() -> dict:
    """美股日 K：obb.equity.price.historical('NVDA', provider='yfinance')。"""
    from openbb import obb

    t0 = time.time()
    res = obb.equity.price.historical(
        "NVDA",
        provider="yfinance",
        start_date="2026-06-01",
        end_date="2026-08-26",
    )
    df = res.to_dataframe()
    return {
        "ok": True,
        "rows": int(len(df)),
        "cols": [str(c) for c in df.columns][:8],
        "first": str(df.index[0]) if len(df) else None,
        "last": str(df.index[-1]) if len(df) else None,
        "last_close": float(df["close"].iloc[-1]) if len(df) and "close" in df else None,
        "elapsed_s": round(time.time() - t0, 1),
    }


def probe_crypto_hist() -> dict:
    """加密日 K：obb.crypto.price.historical('BTC-USD', provider='yfinance')。"""
    from openbb import obb

    t0 = time.time()
    res = obb.crypto.price.historical(
        "BTC-USD", provider="yfinance",
        start_date="2026-06-01", end_date="2026-08-26",
    )
    df = res.to_dataframe()
    return {
        "ok": True,
        "rows": int(len(df)),
        "first": str(df.index[0]) if len(df) else None,
        "last": str(df.index[-1]) if len(df) else None,
        "elapsed_s": round(time.time() - t0, 1),
    }


def run_with_timeout(fn, timeout: int) -> dict:
    """子线程执行 + 超时保护。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return {"ok": False, "error": f"timeout>{timeout}s（跨境源不可达或过慢）"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="仅框架加载自检")
    args = parser.parse_args()

    report: dict = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "quick": args.quick}
    try:
        report["framework"] = probe_framework()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 框架加载失败: {type(exc).__name__}: {exc}")
        return 1

    if not args.quick:
        print("[..] 探测美股日K NVDA(yfinance) …")
        report["equity_hist_nvda"] = run_with_timeout(probe_equity_hist, PER_CALL_TIMEOUT)
        print("[..] 探测加密日K BTC-USD(yfinance) …")
        report["crypto_hist_btc"] = run_with_timeout(probe_crypto_hist, PER_CALL_TIMEOUT)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "obb_smoke_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[OK] 报告已写: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
