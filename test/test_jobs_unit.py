"""
Unit tests for mcp_tools._jobs — in-memory job registry.

These test the JobRegistry directly without requiring the MCP server.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcp_tools._jobs import JobRegistry, JobStatus


@pytest.fixture
def registry():
    return JobRegistry()


# ───────────────────────────────────────────────────────────────────
# submit and get
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_returns_job_id(registry):
    async def noop():
        return {"ok": True}

    job_id = registry.submit("test_tool", noop())
    assert isinstance(job_id, str)
    assert len(job_id) == 8


@pytest.mark.asyncio
async def test_get_pending_job(registry):
    async def slow():
        await asyncio.sleep(10)

    job_id = registry.submit("test_tool", slow())
    job = registry.get(job_id)
    assert job is not None
    assert job["tool_name"] == "test_tool"
    assert job["status"] in ("pending", "running")
    registry.cancel(job_id)


@pytest.mark.asyncio
async def test_job_transitions_to_done(registry):
    async def quick():
        return {"result": 42}

    job_id = registry.submit("test_tool", quick())
    await asyncio.sleep(0.1)

    job = registry.get(job_id)
    assert job["status"] == "done"
    assert job["result"] == {"result": 42}
    assert job["finished_at"] != ""


@pytest.mark.asyncio
async def test_job_transitions_to_failed(registry):
    async def failing():
        raise RuntimeError("boom")

    job_id = registry.submit("test_tool", failing())
    await asyncio.sleep(0.1)

    job = registry.get(job_id)
    assert job["status"] == "failed"
    assert "boom" in job["error"]


def test_get_nonexistent_returns_none(registry):
    assert registry.get("no-such-id") is None


# ───────────────────────────────────────────────────────────────────
# list_all
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_all(registry):
    async def noop():
        return {}

    registry.submit("tool_a", noop())
    registry.submit("tool_b", noop())
    await asyncio.sleep(0.1)

    jobs = registry.list_all()
    assert len(jobs) == 2
    names = {j["tool_name"] for j in jobs}
    assert names == {"tool_a", "tool_b"}


# ───────────────────────────────────────────────────────────────────
# cancel
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_running_job(registry):
    async def slow():
        await asyncio.sleep(60)

    job_id = registry.submit("test_tool", slow())
    await asyncio.sleep(0.1)

    assert registry.cancel(job_id) is True
    job = registry.get(job_id)
    assert job["status"] == "failed"
    assert "Cancelled" in job["error"]


@pytest.mark.asyncio
async def test_cancel_finished_job(registry):
    async def quick():
        return {}

    job_id = registry.submit("test_tool", quick())
    await asyncio.sleep(0.1)

    assert registry.cancel(job_id) is False


def test_cancel_nonexistent(registry):
    assert registry.cancel("no-such-id") is False
