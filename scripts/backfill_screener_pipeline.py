"""高股息选股 → 工商画像/知识产权回填管线（半自动）。

用途：跑高股息选股器 Top N，生成「待回填队列」（output/backfill_queue.json），
标注每只标的是否已回填（天眼查画像 / 智慧芽专利）。MCP 数据源需会话内拉取，
本脚本只负责：① 生成候选清单 ② 比对库内已回填状态 ③ 输出回填优先级。

用法：
    python scripts/backfill_screener_pipeline.py [--top 20] [--min-yield 3.0]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def run_pipeline(top: int = 20, min_yield: float = 3.0,
                 silent_json: bool = False) -> int:
    """执行回填管线：选股 Top N → 比对已回填 → 输出待回填队列 JSON。

    :return: 0 成功；1 数据源不可用
    """
    from ashare_monitor.import_data import (
        get_all_company_profiles,
        get_all_ip_assets,
    )
    from ashare_monitor.screen import screen_dividend

    print(f"== 高股息选股 Top {top}（股息率 ≥ {min_yield}%）==")
    try:
        hits = screen_dividend(top_n=top * 2, min_yield=min_yield)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 选股器拉取失败：{exc}")
        print("   （东财 push2 在沙箱不稳定，请在本机运行：")
        print(f"     python scripts/backfill_screener_pipeline.py --top {top}）")
        return 1
    hits = hits[:top]

    profiles = get_all_company_profiles()
    ips = get_all_ip_assets()

    def _covered(company: str, table: dict) -> bool:
        return any(company in k or k in company for k in table)

    queue = []
    print(f"\n{'代码':<8}{'名称':<10}{'股息率%':>8}{'市值(亿)':>10}  {'画像':<6}{'专利':<6}{'优先级'}")
    for h in hits:
        has_p = _covered(h.name, profiles)
        has_ip = _covered(h.name, ips)
        if not has_p and not has_ip:
            pri = "★ 高" if h.dividend_yield and h.dividend_yield >= 5 else "中"
        elif not has_ip:
            pri = "补专利"
        else:
            pri = "已齐"
        mv = (h.market_value or 0) / 1e8
        print(f"{h.code:<8}{h.name:<10}{(h.dividend_yield or 0):>7.2f}%"
              f"{mv:>9.0f}  "
              f"{'✅' if has_p else '—':<6}{'✅' if has_ip else '—':<6}{pri}")
        if not (has_p and has_ip):
            queue.append({
                "code": h.code, "name": h.name,
                "dividend_yield": h.dividend_yield,
                "market_value_yi": round(mv, 1),
                "need_profile": not has_p, "need_ip": not has_ip,
                "priority": pri,
            })

    if silent_json:
        print(json.dumps(queue, ensure_ascii=False, indent=2))
        return 0
    out = ROOT / "output" / "backfill_queue.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(queue, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n待回填队列（{len(queue)} 只）→ {out}")
    if queue:
        print("下一步（会话内）：对队列中 need_profile 标的调天眼查 MCP，"
              "need_ip 标的调智慧芽 MCP，经 scripts/backfill_*.py 落库。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="高股息选股 → 回填管线")
    ap.add_argument("--top", type=int, default=20, help="Top N（默认 20）")
    ap.add_argument("--min-yield", type=float, default=3.0,
                    help="最小股息率 %（默认 3.0）")
    ap.add_argument("--json", action="store_true",
                    help="仅输出待回填队列 JSON（供后续会话 MCP 回填）")
    args = ap.parse_args()
    return run_pipeline(args.top, args.min_yield, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
