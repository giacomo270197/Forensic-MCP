"""
Tests for job management tools: get_job_status, list_jobs, cancel_job.
"""

import asyncio
import pytest
from conftest import parse_tool_result


# ───────────────────────────────────────────────────────────────────
# get_job_status
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_job_status_unknown_job(mcp):
    result = parse_tool_result(
        await mcp.call_tool("get_job_status", {"job_id": "nonexistent_id"})
    )
    assert result["status"] == "failed"
    assert "No job found" in result["error"]


@pytest.mark.asyncio
async def test_get_job_status_valid_job(mcp):
    submitted = parse_tool_result(
        await mcp.call_tool("run_analysis_script", {"script": "print(1)"})
    )
    job_id = submitted["job_id"]

    result = parse_tool_result(
        await mcp.call_tool("get_job_status", {"job_id": job_id})
    )
    assert result["job_id"] == job_id
    assert result["status"] in ("pending", "running", "done", "failed")
    assert result["tool_name"] == "run_analysis_script"
    assert "created_at" in result


@pytest.mark.asyncio
async def test_get_job_status_transitions_to_done(mcp):
    submitted = parse_tool_result(
        await mcp.call_tool("run_analysis_script", {"script": "pass"})
    )
    job_id = submitted["job_id"]

    for _ in range(30):
        result = parse_tool_result(
            await mcp.call_tool("get_job_status", {"job_id": job_id})
        )
        if result["status"] == "done":
            break
        await asyncio.sleep(1)

    assert result["status"] == "done"
    assert result["finished_at"] != ""


@pytest.mark.asyncio
async def test_get_job_status_has_timestamps(mcp):
    submitted = parse_tool_result(
        await mcp.call_tool("run_analysis_script", {"script": "pass"})
    )
    job_id = submitted["job_id"]

    # Wait for completion
    for _ in range(30):
        result = parse_tool_result(
            await mcp.call_tool("get_job_status", {"job_id": job_id})
        )
        if result["status"] == "done":
            break
        await asyncio.sleep(1)

    assert result["created_at"] != ""
    assert result["started_at"] != ""
    assert result["finished_at"] != ""


# ───────────────────────────────────────────────────────────────────
# list_jobs
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_jobs_returns_list(mcp):
    result = parse_tool_result(await mcp.call_tool("list_jobs", {}))
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_list_jobs_includes_submitted_job(mcp):
    submitted = parse_tool_result(
        await mcp.call_tool("run_analysis_script", {"script": "pass"})
    )
    job_id = submitted["job_id"]

    jobs = parse_tool_result(await mcp.call_tool("list_jobs", {}))
    job_ids = [j["job_id"] for j in jobs]
    assert job_id in job_ids


@pytest.mark.asyncio
async def test_list_jobs_entries_have_required_fields(mcp):
    # Ensure at least one job exists
    await mcp.call_tool("run_analysis_script", {"script": "pass"})

    jobs = parse_tool_result(await mcp.call_tool("list_jobs", {}))
    assert len(jobs) > 0
    for job in jobs:
        assert "job_id" in job
        assert "tool_name" in job
        assert "status" in job
        assert "created_at" in job


# ───────────────────────────────────────────────────────────────────
# cancel_job
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_nonexistent_job(mcp):
    result = parse_tool_result(
        await mcp.call_tool("cancel_job", {"job_id": "no_such_job"})
    )
    assert result["cancelled"] is False
    assert "not found or already finished" in result["message"]


@pytest.mark.asyncio
async def test_cancel_running_job(mcp):
    # Start a long-running script
    submitted = parse_tool_result(
        await mcp.call_tool(
            "run_analysis_script",
            {"script": "import time; time.sleep(300)"},
        )
    )
    job_id = submitted["job_id"]

    # Give it a moment to start
    await asyncio.sleep(2)

    result = parse_tool_result(
        await mcp.call_tool("cancel_job", {"job_id": job_id})
    )
    assert result["job_id"] == job_id
    assert result["cancelled"] is True


@pytest.mark.asyncio
async def test_cancel_already_finished_job(mcp):
    submitted = parse_tool_result(
        await mcp.call_tool("run_analysis_script", {"script": "pass"})
    )
    job_id = submitted["job_id"]

    # Wait for completion
    for _ in range(30):
        status = parse_tool_result(
            await mcp.call_tool("get_job_status", {"job_id": job_id})
        )
        if status["status"] == "done":
            break
        await asyncio.sleep(1)

    result = parse_tool_result(
        await mcp.call_tool("cancel_job", {"job_id": job_id})
    )
    assert result["cancelled"] is False
