"""
Tests for tool discovery: verifies the server exposes the expected set of tools.
"""

import pytest
from conftest import parse_tool_result


# Tools defined in modules we ARE testing (excluding tools.py and composite.py)
EXPECTED_TOOLS = {
    # forensics_mcp.py
    "health_check",
    "run_analysis_script",
    # findings.py
    "add_timeline_entry",
    "write_finding",
    "summarise_findings",
    # jobs_management.py
    "get_job_status",
    "list_jobs",
    "cancel_job",
    # questions.py
    "submit_question",
    "get_next_question",
    "submit_answer",
    "get_question",
    "check_children",
    # sqlite.py
    "list_tables",
    "get_table_columns",
    "query_table",
}

# Tools defined in investigation_tools.py (may or may not be registered)
INVESTIGATION_TOOLS = {
    "initialize_plan",
    "get_plan_summary",
    "get_current_phase",
    "list_phases",
    "add_goal",
    "complete_goal",
    "add_phase",
    "skip_phase",
}

# Tools we deliberately exclude from testing
EXCLUDED_TOOLS = {
    # tools.py
    "run_hayabusa",
    "run_pecmd",
    "run_recmd",
    "run_amcacheparser",
    "run_appcompatcacheparser",
    "run_jlecmd",
    "run_lecmd",
    "run_mftecmd",
    "run_rbcmd",
    "run_recentfilecacheparser",
    "run_sbecmd",
    "run_srumecmd",
    "run_sumecmd",
    # composite.py
    "windows_full_disk",
}


@pytest.mark.asyncio
async def test_server_exposes_expected_tools(mcp):
    """All tools we test should be registered on the server."""
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}

    missing = EXPECTED_TOOLS - tool_names
    assert not missing, f"Expected tools missing from server: {missing}"


@pytest.mark.asyncio
async def test_server_lists_tools(mcp):
    """Server should expose at least the expected tool count."""
    tools = await mcp.list_tools()
    assert len(tools) >= len(EXPECTED_TOOLS)


@pytest.mark.asyncio
async def test_excluded_tools_exist_on_server(mcp):
    """Verify that excluded tools (tools.py/composite.py) ARE on the server,
    confirming we're deliberately skipping them, not missing them."""
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}

    present = EXCLUDED_TOOLS & tool_names
    # At least some should be present (depending on tools.yaml config)
    assert len(present) > 0, (
        "None of the excluded tools found on server — "
        "check that the server is running with tools.yaml loaded."
    )


@pytest.mark.asyncio
async def test_investigation_tools_availability(mcp):
    """Report whether investigation tools are registered (informational)."""
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}

    available = INVESTIGATION_TOOLS & tool_names
    missing = INVESTIGATION_TOOLS - tool_names

    if missing:
        pytest.skip(
            f"Investigation tools not registered: {missing}. "
            "Call register_investigation_tools(mcp) in forensics_mcp.py to enable."
        )
    assert available == INVESTIGATION_TOOLS
