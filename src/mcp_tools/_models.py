"""
mcp_tools._models
=================
Pydantic output models shared across all tool modules.
FastMCP uses these to generate a typed outputSchema for each tool,
which MCP clients (e.g. Claude Desktop) can use to validate and
understand tool responses.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CommandResult(BaseModel):
    """Result returned by every Zimmerman CLI tool wrapper."""

    success: bool = Field(
        description="True if the process exited with returncode 0."
    )
    returncode: int = Field(
        description="Exit code of the subprocess."
    )
    stdout: str = Field(
        description="Captured standard output from the process."
    )
    stderr: str = Field(
        description="Captured standard error from the process."
    )
    command: str = Field(
        description="The full command string that was executed."
    )
    output_dir: str = Field(
        description="Absolute path to the directory where output files were written."
    )


class HealthToolStatus(BaseModel):
    """Status of a single configured tool as reported by health_check."""

    name: str = Field(description="Human-readable tool name (from tools.yaml).")
    mcp_tool: str = Field(description="MCP tool function name.")
    description: str = Field(description="What the tool does (from tools.yaml).")
    executable: str = Field(description="Configured path to the tool binary.")
    executable_found: bool = Field(description="Whether the binary exists on disk.")
    implementation: str = Field(description="Path to the mcp_tools/*.py module.")
    implementation_found: bool = Field(description="Whether the module file exists.")
    loaded: bool = Field(description="Whether the tool was successfully registered at startup.")


class HealthResult(BaseModel):
    """Result returned by health_check."""

    status: str = Field(
        description='"ok" if all tools loaded, "degraded" if any failed.'
    )
    timestamp: str = Field(description="UTC timestamp of the health check (ISO 8601).")
    config_file: str = Field(description="Absolute path to the tools.yaml config file.")
    output_dir: str = Field(description="Absolute path to the root output directory.")
    python_version: str = Field(description="Python version running the server.")
    tools_available: list[HealthToolStatus] = Field(
        description="One entry per tool defined in tools.yaml."
    )
    tools_failed: list[str] = Field(
        description="mcp_tool names that failed to register at startup."
    )


class ScriptResult(BaseModel):
    """Result returned by run_analysis_script."""

    success: bool = Field(description="True if the script exited with returncode 0.")
    returncode: int = Field(description="Exit code of the Python subprocess.")
    stdout: str = Field(description="Captured standard output from the script.")
    stderr: str = Field(description="Captured standard error from the script.")
    script_executed: str = Field(description="The full script that was run, including the injected DATA_FILE preamble.")


class JobSubmitted(BaseModel):
    """Returned immediately when a long-running tool is called."""

    job_id: str = Field(
        description="Unique identifier for this job. Pass to get_job_status to poll for completion."
    )
    tool_name: str = Field(
        description="The tool that was invoked."
    )
    status: str = Field(
        description='Always "pending" at submission time.'
    )
    message: str = Field(
        description="Human-readable confirmation message."
    )


class JobStatusResult(BaseModel):
    """Returned by get_job_status and list_jobs."""

    job_id: str = Field(description="Unique job identifier.")
    tool_name: str = Field(description="The tool that was invoked.")
    status: str = Field(description='"pending", "running", "done", or "failed".')
    result: dict | None = Field(default=None, description="Tool output, populated when status is done.")
    error: str = Field(default="", description="Error message, populated when status is failed.")
    created_at: str = Field(description="UTC ISO 8601 timestamp when the job was submitted.")
    started_at: str = Field(description="UTC ISO 8601 timestamp when execution began.")
    finished_at: str = Field(description="UTC ISO 8601 timestamp when execution completed.")