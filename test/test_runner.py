"""
Unit tests for mcp_tools._runner — subprocess helpers.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcp_tools._runner import run_cmd, run_cmd_async, safe_stem


# ───────────────────────────────────────────────────────────────────
# safe_stem
# ───────────────────────────────────────────────────────────────────


def test_safe_stem_basic():
    assert safe_stem("/path/to/file.csv") == "file"


def test_safe_stem_spaces():
    assert safe_stem("/path/to/my file.csv") == "my_file"


def test_safe_stem_empty():
    assert safe_stem("") == "output"


# ───────────────────────────────────────────────────────────────────
# run_cmd (synchronous)
# ───────────────────────────────────────────────────────────────────


def test_run_cmd_success():
    result = run_cmd([sys.executable, "-c", "print('hello')"])
    assert result["success"] is True
    assert result["returncode"] == 0


def test_run_cmd_failure():
    result = run_cmd([sys.executable, "-c", "raise SystemExit(1)"])
    assert result["success"] is False
    assert result["returncode"] == 1


def test_run_cmd_not_found():
    result = run_cmd(["this_executable_does_not_exist_xyz"])
    assert result["success"] is False
    assert "not found" in result["stderr"].lower()


def test_run_cmd_timeout():
    result = run_cmd([sys.executable, "-c", "import time; time.sleep(60)"], timeout=1)
    assert result["success"] is False
    assert "timed out" in result["stderr"].lower()


# ───────────────────────────────────────────────────────────────────
# run_cmd_async
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_cmd_async_success():
    result = await run_cmd_async([sys.executable, "-c", "print('async')"])
    assert result["success"] is True
    assert result["returncode"] == 0


@pytest.mark.asyncio
async def test_run_cmd_async_failure():
    result = await run_cmd_async([sys.executable, "-c", "raise SystemExit(2)"])
    assert result["success"] is False
    assert result["returncode"] == 2


@pytest.mark.asyncio
async def test_run_cmd_async_not_found():
    result = await run_cmd_async(["this_executable_does_not_exist_xyz"])
    assert result["success"] is False
    assert "not found" in result["stderr"].lower()


@pytest.mark.asyncio
async def test_run_cmd_async_timeout():
    result = await run_cmd_async(
        [sys.executable, "-c", "import time; time.sleep(60)"], timeout=1
    )
    assert result["success"] is False
    assert "timed out" in result["stderr"].lower()


@pytest.mark.asyncio
async def test_run_cmd_async_progress_callback():
    lines = []

    async def cb(line):
        lines.append(line)

    # Write to stderr so the callback sees it
    await run_cmd_async(
        [sys.executable, "-c", "import sys; sys.stderr.write('progress\\n')"],
        progress_cb=cb,
    )
    assert len(lines) >= 1
    assert "progress" in lines[0]
