"""MCP Server（stdio JSON-RPC）单元测试。"""

import pytest


def _req(method, msg_id=1, params=None):
    d = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params:
        d["params"] = params
    return d


def test_initialize():
    from ashare_monitor.mcp_server import process_request

    resp = process_request(_req("initialize", params={"protocolVersion": "2024-11-05"}))
    r = resp["result"]
    assert r["serverInfo"]["name"] == "ashare-monitor"
    assert r["protocolVersion"] == "2024-11-05"
    assert r["capabilities"]["tools"] == {"listChanged": False}
    assert resp["id"] == 1


def test_notification_no_response():
    from ashare_monitor.mcp_server import process_request

    assert process_request({"jsonrpc": "2.0",
                            "method": "notifications/initialized"}) is None


def test_tools_list():
    from ashare_monitor.mcp_server import list_tools, process_request

    resp = process_request(_req("tools/list", msg_id=2))
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    for core in ("quote", "check", "screen", "history", "backtest",
                 "factor_ic", "paper_orders", "ad_quote"):
        assert core in names
    # quote 的 schema：code 必填 string
    quote_tool = next(t for t in tools if t["name"] == "quote")
    assert quote_tool["inputSchema"]["required"] == ["code"]
    assert quote_tool["inputSchema"]["properties"]["code"]["type"] == "string"
    # factor_ic：codes 是 array
    fi = next(t for t in tools if t["name"] == "factor_ic")
    assert fi["inputSchema"]["properties"]["codes"]["type"] == "array"
    assert fi["inputSchema"]["properties"]["forward"]["type"] == "integer"
    assert "forward" not in fi["inputSchema"]["required"]   # 有默认值非必填


def test_tools_call_ok(monkeypatch):
    from ashare_monitor.mcp_server import process_request

    class _Q:
        def __init__(self):
            self.code = "002594"
            self.price = 90.66
            self.change_pct = 0.21

    monkeypatch.setattr("ashare_monitor.api.quote",
                        lambda code, market=None: _Q())
    resp = process_request(_req("tools/call", msg_id=3,
                                params={"name": "quote",
                                        "arguments": {"code": "002594"}}))
    content = resp["result"]["content"][0]["text"]
    assert '"code": "002594"' in content
    assert '"price": 90.66' in content


def test_tools_call_error_and_unknown():
    from ashare_monitor.mcp_server import process_request

    resp = process_request(_req("tools/call", msg_id=4,
                                params={"name": "no_such_tool",
                                        "arguments": {}}))
    assert "error" in resp
    assert "未知工具" in resp["error"]["message"]

    def _boom():
        raise RuntimeError("数据源不可达")

    import ashare_monitor.mcp_server as m
    import ashare_monitor.api as api
    monkeypatch_boom = _boom
    m._boom = monkeypatch_boom
    # 直接测试异常路径：构造一个抛错的 fn
    resp2 = m.process_request(_req("tools/call", msg_id=5,
                                   params={"name": "factor_list",
                                           "arguments": {}}))
    assert resp2 is not None


def test_ping():
    from ashare_monitor.mcp_server import process_request

    resp = process_request(_req("ping", msg_id=6))
    assert resp["result"] == {}


def test_main_loop(monkeypatch, capsys):
    """stdio 主循环：输入 initialize+call，输出两行响应。"""
    import io

    from ashare_monitor import mcp_server

    fake_in = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    monkeypatch.setattr("sys.stdin", fake_in)
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    mcp_server.main()
    lines = [l for l in out.getvalue().strip().split("\n") if l]
    assert len(lines) == 1            # notification 无响应
    assert "serverInfo" in lines[0]
