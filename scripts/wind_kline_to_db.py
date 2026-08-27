"""Wind MCP K 线落盘文件 → 本地 klines 库。

Wind get_stock_kline 单次最多约 4600 条（截断最早部分），需分段拉取；
本脚本解析落盘 JSON（data.rows），先清空该 code 旧数据再落库（防口径混源）。

用法：python scripts/wind_kline_to_db.py <落盘文件> <code> [--append]
  --append：不清空旧数据（用于同源分段补充）
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ashare_monitor.storage import get_conn, record_klines  # noqa: E402


def parse_wind_rows(raw: str) -> list[tuple]:
    """Wind 落盘 JSON → [(date, open, close, high, low, volume)]。"""
    d = json.loads(raw)
    rows = d.get("data", {}).get("rows") or []
    out = []
    for r in rows:
        date = str(r[0])[:10]          # 2007-09-25T00:00:00+02:00 → 2007-09-25
        def _f(i: int) -> float:
            v = r[i]
            return float(v) if v not in (None, "") else 0.0
        o, c = _f(1), _f(2)
        h, l = _f(3), _f(4)
        vol = _f(6)                    # 第 6 列 VOLUME（第 5 列是 TURNOVER 成交额）
        out.append((date, o, c, h, l, vol))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Wind 落盘 K 线 → 本地库")
    ap.add_argument("file", help="Wind MCP 返回落盘文件路径")
    ap.add_argument("code", help="股票代码（6 位，如 601939）")
    ap.add_argument("--append", action="store_true", help="不清空旧数据（分段补充）")
    args = ap.parse_args()

    raw = Path(args.file).read_text(encoding="utf-8")
    rows = parse_wind_rows(raw)
    if not rows:
        print(f"❌ {args.file} 无 rows")
        return 1

    if not args.append:
        conn = get_conn()
        try:
            cur = conn.execute(
                "DELETE FROM klines WHERE market='ashare' AND code=?",
                (args.code,))
            conn.commit()
            print(f"↳ 清空旧数据 {cur.rowcount} 行（{args.code}）")
        finally:
            conn.close()

    new = record_klines(rows, "ashare", args.code)
    print(f"✅ {args.code}: +{new} 根（{rows[0][0]} ~ {rows[-1][0]}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
