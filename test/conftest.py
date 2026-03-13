"""
Shared fixtures for forensic MCP integration tests.

Assumes the server is running locally in HTTP/SSE mode:
    python src/forensics_mcp.py --sse
"""

import json
import pytest
import pytest_asyncio
from fastmcp import Client


SERVER_URL = "http://127.0.0.1:8000/sse"


def parse_tool_result(result) -> dict | list | str:
    """Extract the parsed JSON (or raw text) from a CallToolResult."""
    text = result.content[0].text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


@pytest_asyncio.fixture
async def mcp():
    """Yield a connected MCP client, then close it."""
    client = Client(SERVER_URL)
    async with client:
        yield client
