"""生成高股息回填队列（腾讯自选股富字段替代源）。

背景：东财 push2 当前网络不可达（RemoteDisconnected），改用已连接
连接器「腾讯自选股」富字段行情 dividend_ratio_ttm 构造真实高股息队列。
数据为 2026-08-25 收盘快照（MCP 会话内批量拉取 43 只高股息常客候选）。

产出：output/backfill_queue.json（与 backfill_screener_pipeline.py 同格式）
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (code, name, dividend_ratio_ttm, total_market_cap_yi)
_QUOTES = [
    ("600066", "宇通客车", 8.34, 664), ("000651", "格力电器", 7.19, 2331),
    ("600741", "华域汽车", 6.51, 484), ("600011", "华能国际", 5.98, 1050),
    ("601166", "兴业银行", 5.92, 3814), ("601919", "中远海控", 5.91, 2606),
    ("601818", "光大银行", 5.70, 1814), ("601169", "北京银行", 5.41, 1087),
    ("600690", "海尔智家", 5.40, 1991), ("600016", "民生银行", 5.40, 1532),
    ("000001", "平安银行", 5.14, 2249), ("600036", "招商银行", 5.10, 9962),
    ("600019", "宝钢股份", 5.08, 1274), ("601318", "中国平安", 4.91, 9961),
    ("000333", "美的集团", 4.86, 6613), ("600585", "海螺水泥", 4.83, 929),
    ("601006", "大秦铁路", 4.72, 938), ("600795", "国电电力", 4.69, 917),
    ("601077", "渝农商行", 4.67, 780), ("600000", "浦发银行", 4.63, 3024),
    ("601328", "交通银行", 4.53, 6327), ("000429", "粤高速A", 4.49, 281),
    ("601658", "邮储银行", 4.33, 6053), ("601857", "中国石油", 4.20, 20480),
    ("601088", "中国神华", 4.09, 10231), ("600377", "宁沪高速", 4.00, 617),
    ("600519", "贵州茅台", 3.99, 16301), ("601398", "工商银行", 3.93, 28156),
    ("600028", "中国石化", 3.73, 6482), ("601988", "中国银行", 3.69, 19784),
    ("601939", "建设银行", 3.65, 27887), ("601288", "农业银行", 3.64, 23974),
    ("601225", "陕西煤业", 3.57, 2571), ("600900", "长江电力", 3.54, 6902),
    ("600938", "中国海油", 3.42, 15927), ("000895", "双汇发展", 3.18, 872),
    ("600188", "兖矿能源", 2.30, 2179), ("000625", "长安汽车", 2.32, 704),
    ("600104", "上汽集团", 2.56, 1185), ("002594", "比亚迪", 0.39, 8329),
    ("300750", "宁德时代", 2.18, 17430), ("000002", "万科A", 0.00, 369),
]


def main() -> int:
    from ashare_monitor.import_data import (
        get_all_company_profiles,
        get_all_ip_assets,
    )

    profiles = get_all_company_profiles()
    ips = get_all_ip_assets()

    def _covered(company: str, table: dict) -> bool:
        return any(company in k or k in company for k in table)

    queue = []
    print(f"{'代码':<8}{'名称':<10}{'股息率%':>8}{'市值(亿)':>9}  "
          f"{'画像':<6}{'专利':<6}{'优先级'}")
    for code, name, dy, mv in _QUOTES:
        if dy < 3.0:
            continue
        has_p = _covered(name, profiles)
        has_ip = _covered(name, ips)
        pri = "★ 高" if dy >= 5 else "中"
        if has_p and has_ip:
            pri = "已齐"
        elif has_ip:
            pri = "补画像"
        elif has_p:
            pri = "补专利"
        print(f"{code:<8}{name:<10}{dy:>7.2f}%{mv:>9.0f}  "
              f"{'✅' if has_p else '—':<6}{'✅' if has_ip else '—':<6}{pri}")
        if not (has_p and has_ip):
            queue.append({"code": code, "name": name,
                          "dividend_yield": dy, "market_value_yi": mv,
                          "need_profile": not has_p, "need_ip": not has_ip,
                          "priority": pri})

    out = ROOT / "output" / "backfill_queue.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(queue, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n待回填队列（{len(queue)} 只，股息率 ≥3%）→ {out}")
    print("数据源：腾讯自选股富字段 dividend_ratio_ttm（2026-08-25 快照，"
          "东财 push2 不可达时的替代源，如实标注）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
