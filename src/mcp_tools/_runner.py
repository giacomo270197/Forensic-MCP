"""
mcp_tools._runner
=================
Shared subprocess helper used by every tool module.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

# Type alias for the optional progress callback
ProgressCallback = Callable[[str], Awaitable[None]] | None


def run_cmd(cmd: list[str], timeout: int = 120) -> dict:
    """
    Synchronous subprocess runner — kept for convenience/testing.
    Prefer run_cmd_async() inside MCP tool handlers.
    """
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return {
            "success":    result.returncode == 0,
            "returncode": result.returncode,
        }
    except FileNotFoundError:
        return {"success": False, "returncode": -1, "stdout": "",
                "stderr": f"Executable not found: {cmd[0]}", "command": " ".join(cmd)}
    except subprocess.TimeoutExpired:
        return {"success": False, "returncode": -1, "stdout": "",
                "stderr": f"Command timed out after {timeout}s", "command": " ".join(cmd)}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "returncode": -1, "stdout": "",
                "stderr": str(exc), "command": " ".join(cmd)}


async def run_cmd_async(
    cmd: list[str],
    timeout: int = 120,
    progress_cb: ProgressCallback = None,
) -> dict:
    """
    Asynchronous subprocess runner.

    If *progress_cb* is provided it is called with each line written to
    stderr by the child process as it runs, allowing the caller to forward
    live progress updates to the MCP client (e.g. via ctx.report_progress).

    The event loop is never blocked — other MCP tool calls can proceed
    while this process is executing.
    """
    cmd_str = " ".join(cmd)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return {"success": False, "returncode": -1, "stdout": "",
                "stderr": f"Executable not found: {cmd[0]}", "command": cmd_str}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "returncode": -1, "stdout": "",
                "stderr": str(exc), "command": cmd_str}

    stderr_lines: list[str] = []

    async def _drain_stderr() -> None:
        """Read stderr line by line, firing progress_cb for each line."""
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            decoded = line.decode(errors="replace")
            stderr_lines.append(decoded)
            if progress_cb:
                await progress_cb(decoded)

    try:
        # Drain stderr in the background while also reading stdout and
        # enforcing the timeout — all three race under wait_for.
        stdout_data, _ = await asyncio.wait_for(
            asyncio.gather(
                proc.stdout.read(),
                _drain_stderr(),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {"success": False, "returncode": -1, "stdout": "",
                "stderr": f"Command timed out after {timeout}s", "command": cmd_str}

    await proc.wait()

    return {
        "success":    proc.returncode == 0,
        "returncode": proc.returncode,
        #"stdout":     stdout_data.decode(errors="replace").strip(),
        "stderr":     "".join(stderr_lines).strip(),
        "command":    cmd_str,
    }


def safe_stem(path: str) -> str:
    """Return a filesystem-safe name derived from *path*."""
    return Path(path).stem.replace(" ", "_") or "output"