"""CI 健康检查：MCP 工具数 / API 函数数基线（防新维度漏暴露）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ashare_monitor import api
from ashare_monitor.mcp_server import list_tools

MIN_TOOLS = 23

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
