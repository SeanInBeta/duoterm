import os
import sys

import pytest

mcp = pytest.importorskip("mcp")
anyio = pytest.importorskip("anyio")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


def test_mcp_tools_over_stdio(term):
    async def scenario():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "duoterm.mcp_server"],
            env={**os.environ, "DUOTERM_HOME": str(term.home), "DUOTERM_SESSION": term.session},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert names == {
                    "terminal_status", "terminal_run", "terminal_type", "terminal_keys",
                    "terminal_screen", "terminal_read", "terminal_wait", "terminal_integrate",
                }
                res = await session.call_tool("terminal_run", {"command": "echo via-mcp; false"})
                assert not res.isError
                assert res.content[0].text == "via-mcp\n[exit 1]"
                res = await session.call_tool("terminal_run", {"command": "reboot"})
                assert res.isError and "dangerous" in res.content[0].text
                res = await session.call_tool("terminal_read", {"new_only": True})
                assert "via-mcp" in res.content[0].text
                res = await session.call_tool("terminal_integrate", {})
                assert "integration active" in res.content[0].text
                res = await session.call_tool("terminal_status", {})
                assert "shell_integration: True" in res.content[0].text
                res = await session.call_tool("terminal_run", {"command": "echo invisible; false"})
                assert res.content[0].text == "invisible\n[exit 1]"
                res = await session.call_tool("terminal_screen", {})
                after = res.content[0].text.split("echo invisible; false")[-1]  # earlier runs were not integrated
                assert after.startswith("\ninvisible\n") and "__RT_" not in after

    anyio.run(scenario)
