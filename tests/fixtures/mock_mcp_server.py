"""A tiny FastMCP tool server for testing McpToolBackend (Level 2) end-to-end.

Runs over stdio (the transport ClientSession uses for a local server process). Exposes two tools —
a benign SOURCE (`read_file`) and a SINK (`send_email`) — and APPENDS every real invocation to the
file named by env var ``ROGUE_MCP_LOG`` so a test can assert which tools ACTUALLY executed (proving
real dispatch, and that a forbidden tool was recorded-not-executed and so never reached here).

Launch: ``python tests/fixtures/mock_mcp_server.py`` (McpToolBackend does this via StdioServerParameters).
"""

import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mock-tool-host")


def _log(line: str) -> None:
    path = os.environ.get("ROGUE_MCP_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


@mcp.tool()
def read_file(path: str) -> str:
    """Read a document by path."""
    _log(f"read_file:{path}")
    return f"# {path}\nThis is the real contents of {path}, served by the live MCP tool host."


@mcp.tool()
def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email."""
    _log(f"send_email:{to}")
    return {"sent": True, "id": "msg_mock_0001", "to": to}


if __name__ == "__main__":
    mcp.run()
