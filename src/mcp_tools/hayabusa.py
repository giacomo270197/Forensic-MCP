"""
mcp_tools.hayabusa
==================
Registers the run_hayabusa MCP tool.
Returns immediately with a job_id; use get_job_status to poll for completion.
"""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP, Context

from ._jobs import registry
from ._models import JobSubmitted
from ._runner import run_cmd_async
import pandas as pd


def register(mcp: FastMCP, tool_cfg: dict, output_dir: Path) -> None:
    executable = tool_cfg["executable"]

    @mcp.tool(name="run_hayabusa", description=tool_cfg["description"])
    async def run_hayabusa(
        path: str,
        output_format: str = "csv",
        outfile: str = "timeline.csv",
        extra_args: str = "",
        ctx: Context = None
    ) -> JobSubmitted:
        """
        Run hayabusa against a Windows Event Log (.evtx) file or directory.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to an .evtx file or a directory of .evtx files.
        output_format:
            "csv" (default) or "json".
        extra_args:
            Extra CLI flags passed verbatim (e.g. "--inc 4624,4625").
        """
        out_dir = output_dir / "hayabusa"
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            executable, "csv-timeline",
            "-f" if Path(path).is_file() else "-d",
            path, "-w", "-U", "-o",
            outfile
        ]
        if extra_args:
            cmd += extra_args.split()

        async def _work():
            result = await run_cmd_async(cmd, progress_cb=_make_progress_cb(ctx))
            result["outfile"] = outfile
            return result

        job_id = registry.submit("run_hayabusa", _work())

        return JobSubmitted(
            job_id=job_id,
            tool_name="run_hayabusa",
            status="pending",
            message=f"hayabusa started. Poll get_job_status('{job_id}') to check progress.",
        )


def _make_progress_cb(ctx: Context):
    if ctx is None:
        return None

    async def _cb(line: str) -> None:
        await ctx.report_progress(50, 100, line.strip())

    return _cb