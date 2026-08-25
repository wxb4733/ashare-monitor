"""独立 Obsidian 知识库（vault）管理。

在项目内创建一个可被 Obsidian 直接打开的独立库：
- obsidian-vault/.obsidian/：应用配置（新文件默认放入复盘目录、启用模板）
- obsidian-vault/README.md：知识库首页（自动生成复盘索引）
- obsidian-vault/模板/复盘模板.md：复盘笔记模板
- obsidian-vault/A股复盘/：每日复盘 Markdown（由 review 导出，本地数据不入 git）

CLI：`obsidian init` 初始化，`obsidian index` 重建首页索引。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# .obsidian 基础配置
_APP_JSON = {
    "alwaysUpdateLinks": True,
    "showLineNumber": True,
    "newFileLocation": "folder",
    "newFileFolderPath": "A股复盘",
    "attachmentFolderPath": "附件",
}

_CORE_PLUGINS_JSON = [
    "file-explorer", "global-search", "switcher", "graph",
    "backlink", "outgoing-link", "tag-pane", "page-preview",
    "templates", "daily-notes", "note-composer", "command-palette",
]

_TEMPLATES_JSON = {"folder": "模板"}

_DAILY_NOTES_JSON = {
    "format": "YYYY-MM-DD",
    "folder": "A股复盘",
    "template": "模板/复盘模板",
}

_HOME_MD = """# A 股监控知识库

由 [ashare-monitor](https://github.com/wxb4733/ashare-monitor) 自动维护的独立 Obsidian 库。

## 目录

- `A股复盘/`：每日复盘报告（Markdown，自动导出）
- `汇总报告/`：周报 / 月报 / 年报（Markdown，自动导出）
- `IPO分析/`：IPO 分析报告（Markdown，自动导出）
- `模板/`：复盘笔记模板

## 复盘索引

<!-- INDEX_START -->
<!-- INDEX_END -->

## 汇总报告索引

<!-- REPORT_INDEX_START -->
<!-- REPORT_INDEX_END -->

## IPO 分析索引

<!-- IPO_INDEX_START -->
<!-- IPO_INDEX_END -->

## 策略验证索引

<!-- BACKTEST_INDEX_START -->
<!-- BACKTEST_INDEX_END -->

## 说明

- 每日收盘后运行 `python -m ashare_monitor.main review` 自动生成并导出复盘
- 周 / 月 / 年报：`python -m ashare_monitor.main report --weekly|--monthly|--yearly`
- IPO 分析报告：`python -m ashare_monitor.main ipo --report`
- 信号命中率验证：`python -m ashare_monitor.main verify 002594 --report`
- 多标的定投对比：`python -m ashare_monitor.main backtest 002594 --compare 002594,01211 --chart`
- 复盘包含：大盘指数、技术指标、当日表现、预警、财报速览、公告与研报、近期 IPO
- 汇总报告包含：区间行情表现、预警统计、每日复盘记录、预警明细
- K 线图（ECharts）以链接指向 HTML 报告
- 数据仅供学习与技术研究，不构成投资建议
"""

_TEMPLATE_MD = """---
title: A股复盘 {{date}}
date: {{date}}
tags: [复盘, A股]
---

# A股收盘复盘 {{date}}

> 该笔记由复盘报告导出生成。每日收盘后运行：
> `python -m ashare_monitor.main review`
"""

_VAULT_GITIGNORE = """# Obsidian 本地状态（不入库）
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.obsidian/cache

# 复盘与汇总数据（本地积累，不入库）
A股复盘/
汇总报告/
IPO分析/
策略验证/
附件/
"""


def init_vault(vault_path: str | Path, reports_dir: str = "A股复盘") -> Path:
    """初始化独立 Obsidian 库（幂等，重复执行安全）。"""
    root = Path(vault_path)
    (root / ".obsidian").mkdir(parents=True, exist_ok=True)
    (root / reports_dir).mkdir(parents=True, exist_ok=True)
    (root / "模板").mkdir(parents=True, exist_ok=True)

    # .obsidian 配置（仅在不存在时写入，避免覆盖用户自定义）
    def _write_if_missing(rel: str, content: str) -> None:
        target = root / rel
        if not target.exists():
            target.write_text(content, encoding="utf-8")

    _write_if_missing(".obsidian/app.json", json.dumps(_APP_JSON, ensure_ascii=False, indent=2))
    _write_if_missing(".obsidian/core-plugins.json",
                      json.dumps(_CORE_PLUGINS_JSON, ensure_ascii=False, indent=2))
    _write_if_missing(".obsidian/community-plugins.json", "[]")
    _write_if_missing(".obsidian/templates.json",
                      json.dumps(_TEMPLATES_JSON, ensure_ascii=False, indent=2))
    _write_if_missing(".obsidian/daily-notes.json",
                      json.dumps(_DAILY_NOTES_JSON, ensure_ascii=False, indent=2))
    _write_if_missing(".gitignore", _VAULT_GITIGNORE)

    # 首页与模板
    home = root / "README.md"
    if not home.exists():
        home.write_text(_HOME_MD, encoding="utf-8")
    tpl = root / "模板" / "复盘模板.md"
    if not tpl.exists():
        tpl.write_text(_TEMPLATE_MD, encoding="utf-8")

    # 重建首页索引（幂等更新）
    build_vault_index(root, reports_dir)
    return root


def build_vault_index(vault_path: str | Path, reports_dir: str = "A股复盘") -> Path:
    """重建首页 README 的复盘索引与汇总报告索引。"""
    import re

    root = Path(vault_path)
    home = root / "README.md"
    if not home.exists():
        home.write_text(_HOME_MD, encoding="utf-8")

    reports = sorted(
        (root / reports_dir).glob("review-*.md"),
        key=lambda p: p.name,
    )
    if not reports:
        links = "（暂无复盘记录，运行 `review` 生成）"
    else:
        links = "\n".join(
            f"- [[{reports_dir}/{r.stem}|{r.stem.replace('review-', '复盘 ')}]]"
            for r in reports[-30:]  # 最近 30 篇
        )
    new_index = f"<!-- INDEX_START -->\n{links}\n<!-- INDEX_END -->"

    # 汇总报告索引（周/月/年报）
    summaries = sorted(
        (root / "汇总报告").glob("report-*.md"),
        key=lambda p: p.name,
    )
    if not summaries:
        sum_links = "（暂无汇总报告，运行 `report --weekly|--monthly|--yearly` 生成）"
    else:
        _PERIOD_CN = {"weekly": "周报", "monthly": "月报", "yearly": "年报"}
        sum_lines = []
        for s in summaries[-12:]:
            period_key = s.name.split("-")[1]
            period_name = _PERIOD_CN.get(period_key, period_key)
            report_date = re.search(r"\d{4}-\d{2}-\d{2}", s.name).group(0)
            sum_lines.append(f"- [[汇总报告/{s.stem}|{period_name} {report_date}]]")
        sum_links = "\n".join(sum_lines)
    new_summary_index = f"<!-- REPORT_INDEX_START -->\n{sum_links}\n<!-- REPORT_INDEX_END -->"

    # IPO 分析报告索引
    ipo_reports = sorted(
        (root / "IPO分析").glob("ipo-report-*.md"),
        key=lambda p: p.name,
    )
    if not ipo_reports:
        ipo_links = "（暂无 IPO 分析报告，运行 `ipo --report` 生成）"
    else:
        ipo_links = "\n".join(
            f"- [[IPO分析/{r.stem}|IPO 分析 "
            f"{re.search(r'\d{4}-\d{2}-\d{2}', r.name).group(0)}]]"
            for r in ipo_reports[-12:]
        )
    new_ipo_index = f"<!-- IPO_INDEX_START -->\n{ipo_links}\n<!-- IPO_INDEX_END -->"

    # 策略验证报告索引（信号命中率 + 多标的对比）
    bt_reports = sorted(
        (root / "策略验证").glob("*.md"),
        key=lambda p: p.name,
    )
    if not bt_reports:
        bt_links = "（暂无策略验证报告，运行 `verify --report` / `backtest --compare --chart` 生成）"
    else:
        bt_links = "\n".join(
            f"- [[策略验证/{r.stem}|"
            f"{('命中率' if r.name.startswith('verify') else '定投对比')} "
            f"{re.search(r'\d{4}-\d{2}-\d{2}', r.name).group(0)}]]"
            for r in bt_reports[-12:]
        )
    new_bt_index = f"<!-- BACKTEST_INDEX_START -->\n{bt_links}\n<!-- BACKTEST_INDEX_END -->"

    text = home.read_text(encoding="utf-8")

    def _replace(text: str, marker: str, new: str) -> str:
        start_marker = marker
        end_marker = marker.replace("_START", "_END")
        if start_marker in text:
            import re

            return re.sub(rf"{start_marker}.*?{end_marker}",
                          new, text, flags=re.S)
        if end_marker in text:  # 有结束占位但缺开始占位
            return text.replace(end_marker, new + "\n" + end_marker)
        # 完全缺失：插入到 "## 说明" 之前
        title = new.splitlines()[0].replace(start_marker, "").strip()
        section = f"{title}\n{new}\n"
        if "## 说明" in text:
            return text.replace("## 说明", section + "## 说明", 1)
        return text + "\n" + section

    text = _replace(text, "<!-- INDEX_START -->", new_index)
    text = _replace(text, "<!-- REPORT_INDEX_START -->", new_summary_index)
    text = _replace(text, "<!-- IPO_INDEX_START -->", new_ipo_index)
    text = _replace(text, "<!-- BACKTEST_INDEX_START -->", new_bt_index)
    home.write_text(text, encoding="utf-8")
    logger.info("知识库索引已更新: %s", home)
    return home
