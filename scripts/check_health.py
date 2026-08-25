"""CI 健康检查：MCP 工具数 / API 函数数 / 全 src 语法兼容（3.10）基线。

防两类回归：
  1. 新维度漏暴露为 API/MCP（工具数低于基线）
  2. f-string 反斜杠 / 嵌套引号等仅在 3.10/3.11 触发、3.12+ 才允许的
     语法错误（用 ast.parse(feature_version=(3,10)) 在任意版本提前拦截）
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare_monitor import api
from ashare_monitor.mcp_server import list_tools

MIN_TOOLS = 23
SYNTAX_VERSION = (3, 10)


def scan_syntax(root: Path = ROOT / "src") -> list[tuple[str, int, str]]:
    """用 Python 3.10 语法规则扫描 src 下全部 .py，返回 [(file, line, msg)]。"""
    bad = []
    for f in sorted(root.rglob("*.py")):
        try:
            ast.parse(f.read_text(encoding="utf-8"),
                      feature_version=SYNTAX_VERSION)
        except SyntaxError as exc:
            bad.append((str(f.relative_to(ROOT)), exc.lineno or 0,
                        exc.msg or "SyntaxError"))
    return bad


bad_syntax = scan_syntax()
if bad_syntax:
    for f, ln, msg in bad_syntax:
        print(f"❌ {f}:{ln} {msg}")
    raise SystemExit(
        f"❌ {len(bad_syntax)} 处代码不兼容 Python {SYNTAX_VERSION[0]}."
        f"{SYNTAX_VERSION[1]}（f-string 反斜杠/嵌套引号等），请修复")
print(f"✅ 全 src 通过 Python {SYNTAX_VERSION[0]}.{SYNTAX_VERSION[1]} 语法扫描"
      f"（{len(list((ROOT / 'src').rglob('*.py')))} 文件）")

tools = list_tools()
api_fns = [n for n in dir(api)
           if not n.startswith("_") and callable(getattr(api, n))
           and getattr(getattr(api, n), "__module__", "") == "ashare_monitor.api"]

print(f"✅ MCP 工具 {len(tools)} 个（基线 >= {MIN_TOOLS}）")
print(f"✅ API 函数 {len(api_fns)} 个")
if len(tools) != len(api_fns):
    print(f"⚠️ 工具/函数数不一致：MCP {len(tools)} vs API {len(api_fns)}"
          "（api 含无参数工具或被过滤项，正常）")
assert len(tools) >= MIN_TOOLS, \
    f"❌ MCP 工具数 {len(tools)} 低于基线 {MIN_TOOLS}，新维度应同步暴露为 API/MCP"
print("✅ 健康检查通过")
