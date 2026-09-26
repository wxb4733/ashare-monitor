@echo off
rem MCP server launcher — guarantees DB_PATH (data/ashare_monitor.db) resolves
rem to the repo root regardless of the caller's working directory.
cd /d E:\github\ashare-monitor
".venv\Scripts\ashare-monitor.exe" mcp
