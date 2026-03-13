import asyncio
from fastmcp import Client, FastMCP

"""
A FastMCP client, mainly meant for testing without using Claude tokens.
"""

client = Client("http://127.0.0.1:8000/sse")

async def main():
    async with client:
        await client.ping()

        # List available operations
        #tools = await client.list_tools()
        result = await client.call_tool("tool name", {"tool param key": "tool param value"})

asyncio.run(main())