"""命令自动文档生成（akshare 模式：从 argparse 生成 API 参考）。

用法：
    python -m ashare_monitor.docs_gen            # 生成 docs/commands.md
    python -m ashare_monitor.docs_gen --stdout   # 打印不落盘

文档来源：main.build_parser() 的全部子命令 + 参数（help/choices/默认值），
与 CLI 行为永远一致——改命令不用改文档（akshare 接口文档自动生成的思路）。
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

# 命令分类（按业务域）
CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("监控", ("monitor", "once", "scan", "radar", "fundflow", "north",
              "block", "lhb", "rating", "pledge", "insider", "site", "gov",
              "litigation", "events", "holders")),
    ("体检与分析", ("check", "doctor", "analyze", "advice", "indicator",
                   "timing", "verify", "profile", "backtest")),
    ("选股", ("screen",)),
    ("历史与回填", ("backfill", "backfill_kline", "history",
                   "backfill_indicators", "backfill_sgr", "backtest_hold")),
    ("报告与导出", ("report", "review", "period", "export", "obsidian")),
    ("策略与交易", ("strategy", "portfolio", "position", "paper", "rebalance")),
    ("数据与资讯", ("news", "financial", "ipo", "ad", "arxiv", "hf")),
]


def _category_of(cmd: str) -> str:
    for name, cmds in CATEGORIES:
        if cmd in cmds:
            return name
    return "其他"


def _iter_commands(parser: argparse.ArgumentParser) -> list[tuple[str, argparse.ArgumentParser, str, str]]:
    """返回 [(name, sub_parser, help, category)]。"""
    out = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {a.dest: a.help or ""
                     for a in getattr(action, "_choices_actions", [])}
            for name, sub in action.choices.items():
                out.append((name, sub, helps.get(name, ""),
                            _category_of(name)))
    return sorted(out, key=lambda x: x[3])


def _arg_rows(sub: argparse.ArgumentParser) -> list[tuple[str, str, str, str]]:
    """返回 [(参数, 必填, 默认, 说明)]。"""
    rows = []
    for a in sub._actions:
        if isinstance(a, argparse._HelpAction):
            continue
        opts = a.option_strings or [a.dest]
        name = ", ".join(opts)
        if isinstance(a, argparse._StoreAction) and a.required:
            req = "是"
        elif opts and opts[0].startswith("--"):
            req = "否"
        else:
            req = "是"
        default = a.default
        if default is None:
            default_s = "—"
        elif isinstance(default, bool):
            default_s = "True" if default else "—"
        else:
            default_s = str(default)
        help_s = (a.help or "").replace("\n", " ")
        rows.append((name, req, default_s, help_s))
    return rows


def generate_commands_md() -> str:
    """生成 commands.md 全文。"""
    from .main import build_parser

    parser = build_parser()
    commands = _iter_commands(parser)
    lines = [
        "# ashare-monitor 命令参考",
        "",
        f"> 自动生成于 {datetime.now():%Y-%m-%d %H:%M}（scripts/gen_docs.py），勿手改",
        f"> 共 {len(commands)} 个命令；命令行 `--help` 与本文档始终一致",
        "",
        "## 命令总览",
        "",
    ]
    cur = None
    for name, sub, help_s, cat in commands:
        if cat != cur:
            lines.append(f"### {cat}")
            lines.append("")
            cur = cat
        lines.append(f"- `{name}` — {help_s or '（无描述）'}")
    lines.append("")
    lines.append("## 命令详情")
    lines.append("")
    for name, sub, help_s, cat in commands:
        lines.append(f"### {name}")
        lines.append("")
        lines.append(help_s or "（无描述）")
        lines.append("")
        rows = _arg_rows(sub)
        if rows:
            lines.append("| 参数 | 必填 | 默认 | 说明 |")
            lines.append("|---|---|---|---|")
            for r in rows:
                lines.append("| " + " | ".join(r) + " |")
        else:
            lines.append("无参数")
        lines.append("")
    return "\n".join(lines)


def write_commands_md(path: str | Path = "docs/commands.md") -> str:
    """写入文档，返回路径。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_commands_md(), encoding="utf-8")
    return str(target)


if __name__ == "__main__":
    import sys

    if "--stdout" in sys.argv:
        print(generate_commands_md())
    else:
        print(f"已生成 {write_commands_md()}")
