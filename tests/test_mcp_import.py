"""Regression: duoterm-mcp crashed at import when mcp 2.x was installed (FastMCP was renamed)."""

import pytest

pytest.importorskip("mcp")
anyio = pytest.importorskip("anyio")


def test_mcp_server_imports_and_registers_tools():
    from duoterm import mcp_server

    async def tool_names():
        return {t.name for t in await mcp_server.mcp.list_tools()}

    assert anyio.run(tool_names) == {
        "terminal_status", "terminal_run", "terminal_type", "terminal_keys",
        "terminal_screen", "terminal_read", "terminal_wait",
    }
