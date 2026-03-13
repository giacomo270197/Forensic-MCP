"""
Tests for core server tools: health_check, run_analysis_script.
"""

import asyncio
import pytest
from conftest import parse_tool_result


# ───────────────────────────────────────────────────────────────────
# health_check
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_returns_ok(mcp):
    result = parse_tool_result(await mcp.call_tool("health_check", {}))
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_health_check_has_timestamp(mcp):
    result = parse_tool_result(await mcp.call_tool("health_check", {}))
    assert "timestamp" in result
    assert result["timestamp"].endswith("Z")


@pytest.mark.asyncio
async def test_health_check_has_tools_list(mcp):
    result = parse_tool_result(await mcp.call_tool("health_check", {}))
    assert "tools_available" in result
    assert isinstance(result["tools_available"], list)
    assert len(result["tools_available"]) > 0


@pytest.mark.asyncio
async def test_health_check_tool_entries_have_required_keys(mcp):
    result = parse_tool_result(await mcp.call_tool("health_check", {}))
    for tool in result["tools_available"]:
        assert "name" in tool
        assert "mcp_tool" in tool
        assert "executable" in tool
        assert "executable_found" in tool


@pytest.mark.asyncio
async def test_health_check_has_python_version(mcp):
    result = parse_tool_result(await mcp.call_tool("health_check", {}))
    assert "python_version" in result


@pytest.mark.asyncio
async def test_health_check_has_output_dir(mcp):
    result = parse_tool_result(await mcp.call_tool("health_check", {}))
    assert "output_dir" in result


@pytest.mark.asyncio
async def test_health_check_has_config_file(mcp):
    result = parse_tool_result(await mcp.call_tool("health_check", {}))
    assert "config_file" in result


# ───────────────────────────────────────────────────────────────────
# run_analysis_script
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_analysis_script_returns_job(mcp):
    result = parse_tool_result(
        await mcp.call_tool("run_analysis_script", {"script": "print('hello')"})
    )
    assert "job_id" in result
    assert result["tool_name"] == "run_analysis_script"
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_run_analysis_script_completes_successfully(mcp):
    submitted = parse_tool_result(
        await mcp.call_tool("run_analysis_script", {"script": "print('ok')"})
    )
    job_id = submitted["job_id"]

    # Poll until done
    for _ in range(30):
        status = parse_tool_result(
            await mcp.call_tool("get_job_status", {"job_id": job_id})
        )
        if status["status"] in ("done", "failed"):
            break
        await asyncio.sleep(1)

    assert status["status"] == "done"
    assert status["result"]["success"] is True
    assert "ok" in status["result"]["stdout"]


@pytest.mark.asyncio
async def test_run_analysis_script_data_file_injection(mcp):
    script = "print(DATA_FILE)"
    submitted = parse_tool_result(
        await mcp.call_tool(
            "run_analysis_script",
            {"script": script, "data_file": "/tmp/test.csv"},
        )
    )
    job_id = submitted["job_id"]

    for _ in range(30):
        status = parse_tool_result(
            await mcp.call_tool("get_job_status", {"job_id": job_id})
        )
        if status["status"] in ("done", "failed"):
            break
        await asyncio.sleep(1)

    assert status["status"] == "done"
    assert "/tmp/test.csv" in status["result"]["stdout"]


@pytest.mark.asyncio
async def test_run_analysis_script_failure_captured(mcp):
    submitted = parse_tool_result(
        await mcp.call_tool(
            "run_analysis_script", {"script": "raise ValueError('boom')"}
        )
    )
    job_id = submitted["job_id"]

    for _ in range(30):
        status = parse_tool_result(
            await mcp.call_tool("get_job_status", {"job_id": job_id})
        )
        if status["status"] in ("done", "failed"):
            break
        await asyncio.sleep(1)

    assert status["status"] == "done"
    assert status["result"]["success"] is False
    assert status["result"]["returncode"] != 0


@pytest.mark.asyncio
async def test_run_analysis_script_timeout(mcp):
    submitted = parse_tool_result(
        await mcp.call_tool(
            "run_analysis_script",
            {"script": "import time; time.sleep(60)", "timeout": 2},
        )
    )
    job_id = submitted["job_id"]

    for _ in range(30):
        status = parse_tool_result(
            await mcp.call_tool("get_job_status", {"job_id": job_id})
        )
        if status["status"] in ("done", "failed"):
            break
        await asyncio.sleep(1)

    assert status["status"] == "done"
    assert status["result"]["success"] is False
    assert "timed out" in status["result"]["stderr"].lower()
