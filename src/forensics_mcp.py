"""
Forensics MCP Server
====================
Config-driven MCP server that loads tool definitions from tools.yaml and
registers all tool implementations from mcp_tools/tools.py.

Adding a new tool
-----------------
1. Add an entry to tools.yaml with name, mcp_tool, executable, description.
2. Add the implementation to mcp_tools/tools.py inside build_tool_registry().
3. Restart the server — no changes to this file needed.

Built with FastMCP (pip install fastmcp pyyaml)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from fastmcp import FastMCP
from mcp_tools._jobs import registry as job_registry
from mcp_tools._models import JobStatusResult, JobSubmitted
from mcp_tools import findings, jobs_management, questions, tools, composite, sqlite

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SRC_DIR         = Path(__file__).parent
SERVER_DIR      = SRC_DIR.parent
CONFIG_FILE     = SERVER_DIR / "tools.yaml"
OUTPUT_DIR      = SERVER_DIR / ".output"
STRATEGIES_FILE = SRC_DIR / "strategies.yaml"

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

def _load_config(config_path: Path) -> list[dict]:
    """Parse tools.yaml and return the list of tool config dicts."""
    if not config_path.exists():
        raise FileNotFoundError(f"Tool config not found: {config_path}")
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    tools = data.get("tools", [])
    if not tools:
        raise ValueError(f"No tools defined in {config_path}")
    return tools


TOOLS_CONFIG: list[dict] = _load_config(CONFIG_FILE)
print(TOOLS_CONFIG)

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="forensics-server",
    instructions=(
        "MCP server for digital forensics. "
        "Wraps configurable CLI tools (Zimmerman and others) and provides "
        "a Python sandbox to analyse their output. "
        "Call health_check to see available tools."
    ),
)

# ---------------------------------------------------------------------------
# Tool registry — all implementations live in mcp_tools/tools.py
# ---------------------------------------------------------------------------

findings.register_tools(mcp, OUTPUT_DIR) 
jobs_management.register_tools(mcp)
questions.register_tools(mcp, OUTPUT_DIR) 
tools.register_tools(mcp, OUTPUT_DIR, TOOLS_CONFIG, Path(SERVER_DIR / "tools"))
composite.register_tools(mcp, OUTPUT_DIR, TOOLS_CONFIG, Path(SERVER_DIR / "tools"))
sqlite.register_tools(mcp, OUTPUT_DIR)

# ---------------------------------------------------------------------------
# Tool: health_check  (always present, not in tools.yaml)
# ---------------------------------------------------------------------------


@mcp.tool()
def health_check() -> dict:
    """
    Check the health of the forensics MCP server.

    Returns
    -------
    - Server status and timestamp
    - List of configured tools with their executable paths and whether
      the executable is present on disk
    - Python version
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    available = []
    for cfg in TOOLS_CONFIG:
        mcp_tool = cfg.get("mcp_tool", "")
        exe_path = Path(SERVER_DIR / 'tools' / (cfg.get("executable", "")) or "")
        available.append({
            "name":             cfg.get("name", mcp_tool),
            "mcp_tool":         mcp_tool,
            "description":      cfg.get("description", "").strip(),
            "executable":       str(exe_path),
            "executable_found": exe_path.exists() if exe_path.parts else None,
        })

    return {
        "status":          "ok",
        "timestamp":       datetime.utcnow().isoformat() + "Z",
        "config_file":     str(CONFIG_FILE),
        "output_dir":      str(OUTPUT_DIR),
        "python_version":  sys.version,
        "tools_available": available,
    }


# ---------------------------------------------------------------------------
# Tool: run_analysis_script  (always present, not in tools.yaml)
# ---------------------------------------------------------------------------


@mcp.tool()
async def run_analysis_script(
    script: str,
    data_file: str = "",
    timeout: int = 3600,
) -> JobSubmitted:
    """
    Execute a Python analysis script against a previously parsed output file.
    Returns immediately with a job_id. Poll get_job_status(job_id) to check
    progress and retrieve results when done.

    The variable DATA_FILE is automatically injected at the top of the script
    so you can reference the parsed CSV/JSON without hardcoding the path::

        import pandas as pd
        df = pd.read_csv(DATA_FILE)
        print(df.head())

    Parameters
    ----------
    script:
        Full Python source code to execute.
    data_file:
        Absolute path to a CSV/JSON file produced by one of the tool runners.
    timeout:
        Maximum seconds to allow the script to run (default 3600).
    """
    import asyncio
    import tempfile
    import traceback

    preamble    = f'DATA_FILE = r"""{data_file}"""\n\n'
    full_script = preamble + script

    async def _work():
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(full_script)
            tmp_path = tmp.name

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return {
                    "success":         False,
                    "returncode":      -1,
                    "stdout":          "",
                    "stderr":          f"Script timed out after {timeout}s",
                    "script_executed": full_script,
                }
            return {
                "success":         proc.returncode == 0,
                "returncode":      proc.returncode,
                "stdout":          stdout.decode(errors="replace").strip(),
                "stderr":          stderr.decode(errors="replace").strip(),
                "script_executed": full_script,
            }
        except Exception:  # noqa: BLE001
            return {
                "success":         False,
                "returncode":      -1,
                "stdout":          "",
                "stderr":          traceback.format_exc(),
                "script_executed": full_script,
            }
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    job_id = job_registry.submit("run_analysis_script", _work())
    return JobSubmitted(
        job_id=job_id,
        tool_name="run_analysis_script",
        status="pending",
        message=f"Analysis script started. Poll get_job_status('{job_id}') to check progress.",
    )

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--sse" in sys.argv:
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
