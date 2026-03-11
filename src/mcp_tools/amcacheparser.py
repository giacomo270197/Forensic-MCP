"""
mcp_tools.amcacheparser
=======================
Registers the run_amcacheparser MCP tool.
Returns immediately with a job_id; use get_job_status to poll for completion.
"""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP, Context

from ._jobs import registry
from ._models import JobSubmitted
from ._runner import run_cmd_async, safe_stem


def register(mcp: FastMCP, tool_cfg: dict, output_dir: Path) -> None:
    executable = tool_cfg["executable"]

    @mcp.tool(name="run_amcacheparser", description=tool_cfg["description"])
    async def run_amcacheparser(
        path: str,
        output_format: str = "csv",
        extra_args: str = "",
        ctx: Context = None,
    ) -> JobSubmitted:
        """
        Run AmcacheParser against an Amcache.hve file.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to Amcache.hve (typically
            C:\\Windows\\appcompat\\Programs\\Amcache.hve).
        output_format:
            "csv" (default) or "json".
        extra_args:
            Extra CLI flags passed verbatim to AmcacheParser.
        """
        out_dir = output_dir / "amcacheparser"
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            executable,
            "-f", path,
            "--csv" if output_format == "csv" else "--json",
            str(out_dir),
        ]
        if extra_args:
            cmd += extra_args.split()

        async def _work():
            result = await run_cmd_async(cmd, progress_cb=_make_progress_cb(ctx))
            result["output_dir"] = str(out_dir)
            return result

        job_id = registry.submit("run_amcacheparser", _work())

        return JobSubmitted(
            job_id=job_id,
            tool_name="run_amcacheparser",
            status="pending",
            message=f"AmcacheParser started. Poll get_job_status('{job_id}') to check progress.",
        )


def _make_progress_cb(ctx: Context):
    if ctx is None:
        return None

    async def _cb(line: str) -> None:
        await ctx.report_progress(50, 100, line.strip())

    return _cb
