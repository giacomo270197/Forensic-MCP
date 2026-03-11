"""
mcp_tools package
=================
Each module in this package exposes a single function:

    register(mcp: FastMCP, tool_cfg: dict) -> None

`tool_cfg` is the dict for that tool as parsed from tools.yaml, e.g.:

    {
        "name":        "EVTXECmd",
        "mcp_tool":    "run_evtxecmd",
        "executable":  "C:\\Tools\\ZimmermanTools\\EVTXECmd.exe",
        "description": "...",
    }

The register function is responsible for decorating and adding its tool(s)
to the FastMCP instance.
"""
