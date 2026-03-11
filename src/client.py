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
        #result = await client.call_tool("windows_full_disk", {"path": "G:"})
        result = await client.call_tool("get_job_status", {"job_id": "4f8d1588"})
        print(result)

asyncio.run(main())