"""
Forensics MCP Host — Ollama edition
====================================
Connects to the forensics MCP server (via stdio) and to a local Ollama
instance, then runs an interactive chat loop where mistral-nemo can call
your forensic tools automatically.

Architecture
------------
  You (terminal)
      ↕
  forensics_host.py          (this file)
      ↕ MCP stdio                ↕ HTTP localhost:11434
  forensics_mcp.py           Ollama / mistral-nemo
      ↕
  Zimmerman Tools

Requirements
------------
  pip install fastmcp httpx

Usage
-----
  python forensics_host.py
  python forensics_host.py --server path/to/forensics_mcp.py
  python forensics_host.py --model mistral-nemo --ollama-url http://localhost:11434
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path

import httpx
from fastmcp import Client


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SERVER = Path(__file__).parent / "forensics_mcp.py"
DEFAULT_MODEL  = "mistral-nemo"
DEFAULT_OLLAMA = "http://localhost:11434"

SYSTEM_PROMPT = """You are a digital forensics assistant with access to tools
that can parse Windows Event Logs, Prefetch files, and Registry hives using
Eric Zimmerman's forensic tools, as well as run Python analysis scripts on
the parsed output.

IMPORTANT RULES:
- When a user asks you to do something, call the appropriate tool immediately.
- After a tool returns a result, you MUST read and report its content to the user.
- Never say a tool failed or that you cannot help if the tool returned data.
- Never apologise or say "try again later" when tool output is present.
- Always summarise the actual tool output in your response.
- Always tell the user where output files were saved."""


# ---------------------------------------------------------------------------
# Ollama client helpers
# ---------------------------------------------------------------------------

def _mcp_to_ollama_tool(tool) -> dict:
    """Convert a FastMCP Tool object to Ollama tool schema format.

    FastMCP 3.x stores the JSON schema under inputSchema;
    fall back to parameters for older versions.
    """
    schema = (
        getattr(tool, "inputSchema", None)
        or getattr(tool, "parameters", None)
        or {"type": "object", "properties": {}}
    )
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": schema,
        },
    }


async def ollama_chat(
    client: httpx.AsyncClient,
    model: str,
    messages: list[dict],
    tools: list[dict],
    ollama_url: str,
) -> dict:
    """Send a chat request to Ollama and return the response message dict."""
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
    }
    response = await client.post(
        f"{ollama_url}/api/chat",
        json=payload,
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()["message"]


# ---------------------------------------------------------------------------
# Agentic tool-call loop
# ---------------------------------------------------------------------------

async def agent_loop(
    mcp_client: Client,
    http_client: httpx.AsyncClient,
    tools: list[dict],
    messages: list[dict],
    model: str,
    ollama_url: str,
) -> str:
    """
    Run the agentic loop for a single user turn:
      1. Ask Ollama what to do.
      2. If it wants to call tools, call them via MCP and feed results back.
      3. Repeat until Ollama returns a plain text response.
    Returns the final assistant text.
    """
    while True:
        assistant_msg = await ollama_chat(
            http_client, model, messages, tools, ollama_url
        )
        messages.append(assistant_msg)

        tool_calls = assistant_msg.get("tool_calls")

        # No tool calls → final answer
        if not tool_calls:
            return assistant_msg.get("content", "")

        # Execute each tool call via MCP
        for tc in tool_calls:
            fn   = tc["function"]
            name = fn["name"]
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)

            print(f"\n  🔧 Calling tool: {name}")
            if args:
                for k, v in args.items():
                    print(f"     {k}: {v}")

            try:
                result = await mcp_client.call_tool(name, args)
                # FastMCP 3.x returns a CallToolResult; extract text content
                if hasattr(result, "content"):
                    tool_output = "\n".join(
                        b.text for b in result.content if hasattr(b, "text")
                    )
                elif hasattr(result, "text"):
                    tool_output = result.text
                else:
                    tool_output = json.dumps(result, default=str)
            except Exception as exc:  # noqa: BLE001
                tool_output = json.dumps({"error": str(exc)})

            print(f"  ✅ Tool returned ({len(tool_output)} chars)")
            try:
                print("  ↳", json.dumps(json.loads(tool_output), indent=4))
            except (json.JSONDecodeError, ValueError):
                print("  ↳", tool_output)
            print()

            # Append tool result — Ollama expects role="tool" with the
            # call id echoed back so the model can match request to response.
            tool_call_id = tc.get("id", name)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": tool_output,
            })


# ---------------------------------------------------------------------------
# Interactive chat
# ---------------------------------------------------------------------------

async def chat(server_path: str, model: str, ollama_url: str) -> None:
    print(f"\n  Forensics Host  •  model: {model}  •  server: {server_path}")
    print("  Type 'quit' or 'exit' to stop, 'reset' to clear history.\n")

    async with Client(server_path) as mcp_client:
        # Discover tools once at startup
        mcp_tools   = await mcp_client.list_tools()
        ollama_tools = [_mcp_to_ollama_tool(t) for t in mcp_tools]
        print(f"  Loaded {len(ollama_tools)} tools: {[t['function']['name'] for t in ollama_tools]}\n")

        async with httpx.AsyncClient() as http_client:
            # Verify Ollama is reachable
            try:
                r = await http_client.get(f"{ollama_url}/api/tags", timeout=5.0)
                r.raise_for_status()
            except Exception as exc:
                print(f"  ❌ Cannot reach Ollama at {ollama_url}: {exc}")
                print("     Make sure Ollama is running:  ollama serve")
                return

            messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

            while True:
                try:
                    user_input = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nBye.")
                    break

                if not user_input:
                    continue

                if user_input.lower() in ("quit", "exit"):
                    print("Bye.")
                    break

                if user_input.lower() == "reset":
                    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                    print("  History cleared.\n")
                    continue

                messages.append({"role": "user", "content": user_input})

                try:
                    reply = await agent_loop(
                        mcp_client, http_client,
                        ollama_tools, messages,
                        model, ollama_url,
                    )
                except httpx.HTTPStatusError as exc:
                    reply = f"Ollama HTTP error: {exc.response.status_code} — {exc.response.text}"
                except Exception as exc:  # noqa: BLE001
                    reply = f"Error: {exc}"

                print(f"\nAssistant: {reply}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Forensics MCP Host (Ollama)")
    p.add_argument(
        "--server",
        default=str(DEFAULT_SERVER),
        help=f"Path to forensics_mcp.py (default: {DEFAULT_SERVER})",
    )
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model name (default: {DEFAULT_MODEL})",
    )
    p.add_argument(
        "--ollama-url",
        default=DEFAULT_OLLAMA,
        help=f"Ollama base URL (default: {DEFAULT_OLLAMA})",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(chat(args.server, args.model, args.ollama_url))