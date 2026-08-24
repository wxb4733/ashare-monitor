"""MCP Server（Model Context Protocol，stdio 传输，零依赖实现）。

在 Python API 层（api.py）之上自动暴露全部函数为 MCP 工具——
任何 AI Agent（WorkBuddy / Claude Desktop / Cursor 等）通过 MCP 连接后
即可直接查询四市场数据与执行分析：

    am.quote("002594")        →  MCP 工具 quote
    am.history("NVDA")        →  MCP 工具 history
    am.screen("dividend")     →  MCP 工具 screen
    am.factor_ic(...)         →  MCP 工具 factor_ic
    am.paper_orders()         →  MCP 工具 paper_orders
    ...

设计：
    - 工具注册表从 api.py 自动生成（函数签名 → JSON Schema），零手工维护
    - 协议：JSON-RPC 2.0 over stdio（initialize / tools/list / tools/call）
    - 不依赖 mcp SDK（手写 ~150 行），符合项目"薄封装、零重依赖"哲学

运行：
    python -m ashare_monitor.mcp_server
    # 或：python -m ashare_monitor.main mcp

MCP 客户端配置（如 WorkBuddy 的 ~/.workbuddy/mcp.json）：
    {"mcpServers": {"ashare": {
        "command": "python",
        "args": ["-m", "ashare_monitor.mcp_server"],
        "cwd": "C:/Users/Administrator/github/ashare-monitor"}}}
"""

from __future__ import annotations

import inspect
import json
import sys
import typing
from typing import get_origin

from . import api

SERVER_NAME = "ashare-monitor"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean",
             dict: "object", list: "array"}


def _arg_schema(fn) -> dict:
    """函数签名 → JSON Schema（参数名/类型/必填）。"""
    try:
        hints = typing.get_type_hints(fn)   # 解析字符串注解（future annotations）
    except Exception:  # noqa: BLE001
        hints = {}
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            continue
        ann = hints.get(name, p.annotation)
        origin = get_origin(ann)
        if origin is list:
            t = "array"
        elif origin is dict:
            t = "object"
        else:
            t = _TYPE_MAP.get(ann, "string")
        props[name] = {"type": t, "description": name}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def _doc_first(fn) -> str:
    doc = (fn.__doc__ or "").strip()
    return doc.split("\n")[0][:120] if doc else ""


def list_tools() -> list[dict]:
    """全部 API 函数 → MCP 工具定义。"""
    tools = []
    for name in dir(api):
        if name.startswith("_"):
            continue
        fn = getattr(api, name)
        if not callable(fn) or getattr(fn, "__module__", "") != "ashare_monitor.api":
            continue
        tools.append({"name": name, "description": _doc_first(fn),
                      "inputSchema": _arg_schema(fn)})
    return tools


def _serialize(obj):
    """任意返回（dataclass/dict/列表）→ JSON 可序列化。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if hasattr(obj, "__dataclass_fields__") or hasattr(obj, "__dict__"):
        return _serialize(vars(obj))
    return str(obj)


def _error(msg_id, text: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601,
                                                      "message": text}}


def process_request(msg: dict) -> dict | None:
    """处理单条 JSON-RPC 消息；notification 返回 None（无需响应）。"""
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id,
                "result": {"tools": list_tools()}}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        fn = getattr(api, name, None)
        if fn is None or not callable(fn):
            return _error(msg_id, f"未知工具 {name}")
        try:
            result = fn(**args)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(_serialize(result),
                                                ensure_ascii=False)}]}}
        except Exception as exc:  # noqa: BLE001
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "isError": True,
                "content": [{"type": "text", "text": f"错误: {exc}"}]}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method.startswith("notifications/"):
        return None
    return _error(msg_id, f"未知方法 {method}")


def main() -> None:
    """stdio 主循环：逐行读 JSON-RPC，逐行回写。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = process_request(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
