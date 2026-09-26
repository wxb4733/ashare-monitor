"""模拟盘 bootstrap 建仓（过渡方案，如实标注）。

背景：东财 push2 实时域在本机网络被整体掐断（http/https/IPv4 全灭，
push2his 历史域正常），高股息全市场选股暂时不可用。为让模拟盘先跑起来
积累净值证据，用「公开常识级高息名单」等权建仓：

    工商银行 / 建设银行 / 农业银行 / 中国银行 /
    中国神华 / 陕西煤业 / 长江电力 / 中国石油 / 大秦铁路 / 中国石化

- 成交价走 fetch_spot_quotes 真实行情（腾讯/新浪源，非杜撰）；
- 名单是透明的人工种子，不是 2026-09-26 当日的真实选股结果；
- push2 恢复后由 strategy rebalance --paper（每月 1 日）自动换成真实筛选结果。

用法（仓库根目录）:
    .venv/Scripts/python.exe scripts/seed_paper_bootstrap.py [--capital 100000]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
os.chdir(REPO)

BOOTSTRAP = [  # (代码, 名称) — 公开常识级高股息名单，透明标注，非实时筛选
    ("601398", "工商银行"), ("601939", "建设银行"),
    ("601288", "农业银行"), ("601988", "中国银行"),
    ("601088", "中国神华"), ("601225", "陕西煤业"),
    ("600900", "长江电力"), ("601857", "中国石油"),
    ("601006", "大秦铁路"), ("600028", "中国石化"),
]


def main() -> None:
    ap = argparse.ArgumentParser(description="模拟盘 bootstrap 建仓")
    ap.add_argument("--capital", type=float, default=100_000.0)
    args = ap.parse_args()

    from ashare_monitor.strategy import TargetPosition, execute_paper_trade

    n = len(BOOTSTRAP)
    per = round(args.capital / n, 2)
    targets = [TargetPosition(code=c, name=nm, weight=round(100 / n, 2),
                              target_value=per)
               for c, nm in BOOTSTRAP]
    print(f"[bootstrap-seed] 模拟建仓 {n} 只等权，目标 "
          f"{args.capital:,.0f} 元（每只 {per:,.0f}），佣金万2.5 印花税万5")
    result = execute_paper_trade(targets, cash=args.capital,
                                 commission_bps=2.5, stamp_duty_bps=5.0)
    fills, rejected = result["fills"], result["rejected"]
    print(f"[bootstrap-seed] 成交 {len(fills)} 笔，拒单 {len(rejected)} 笔，"
          f"剩余现金 {result['cash']:,.0f} 元")
    for f in fills:
        print(f"  Filled  {f.get('code')} {f.get('name')} "
              f"{f.get('shares')}股 @ {f.get('price')}")
    for r in rejected:
        print(f"  Rejected {r.get('code')} {r.get('name')}: {r.get('reason')}")


if __name__ == "__main__":
    main()
