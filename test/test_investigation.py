"""
Tests for investigation planning tools: initialize_plan, get_plan_summary,
get_current_phase, list_phases, add_goal, complete_goal, add_phase, skip_phase.

NOTE: These tools are defined in mcp_tools/investigation_tools.py but may not
be registered on the server (register_investigation_tools must be called in
forensics_mcp.py). Tests will skip gracefully if the tools are unavailable.
"""

import pytest
from conftest import parse_tool_result


async def _tool_available(mcp, tool_name: str) -> bool:
    """Check if a tool is registered on the server."""
    tools = await mcp.list_tools()
    return any(t.name == tool_name for t in tools)


# ───────────────────────────────────────────────────────────────────
# initialize_plan
# ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def _skip_if_unavailable(mcp):
    if not await _tool_available(mcp, "initialize_plan"):
        pytest.skip(
            "Investigation tools not registered on server. "
            "Call register_investigation_tools(mcp) in forensics_mcp.py."
        )


@pytest.mark.asyncio
async def test_initialize_plan_default_phases(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-DEFAULT-001"}
        )
    )
    assert "plan_id" in result
    assert result["case_name"] == "TEST-DEFAULT-001"
    assert len(result["phases"]) == 8

    # First phase should be active
    assert result["phases"][0]["status"] == "active"
    assert result["phases"][0]["name"] == "initial_triage"


@pytest.mark.asyncio
async def test_initialize_plan_custom_phases(mcp):
    custom = [
        {"name": "recon", "description": "Reconnaissance phase"},
        {"name": "exploit", "description": "Exploitation phase"},
    ]
    result = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan",
            {"case_name": "TEST-CUSTOM-001", "custom_phases": custom},
        )
    )
    assert len(result["phases"]) == 2
    assert result["phases"][0]["name"] == "recon"
    assert result["phases"][0]["status"] == "active"
    assert result["phases"][1]["name"] == "exploit"
    assert result["phases"][1]["status"] == "pending"


@pytest.mark.asyncio
async def test_initialize_plan_has_timestamps(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-TS-001"}
        )
    )
    assert "created_at" in result
    assert "updated_at" in result


@pytest.mark.asyncio
async def test_initialize_plan_first_phase_has_started_at(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-START-001"}
        )
    )
    assert result["phases"][0]["started_at"] is not None


@pytest.mark.asyncio
async def test_initialize_plan_remaining_phases_pending(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-PENDING-001"}
        )
    )
    for phase in result["phases"][1:]:
        assert phase["status"] == "pending"


# ───────────────────────────────────────────────────────────────────
# get_plan_summary
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_plan_summary(mcp):
    await mcp.call_tool(
        "initialize_plan", {"case_name": "TEST-SUMMARY-001"}
    )

    result = parse_tool_result(await mcp.call_tool("get_plan_summary", {}))
    assert result["case_name"] == "TEST-SUMMARY-001"
    assert "plan_id" in result
    assert "total_phases" in result
    assert "phase_counts" in result
    assert "current_phase" in result
    assert "open_goals" in result
    assert "closed_goals" in result


@pytest.mark.asyncio
async def test_get_plan_summary_phase_counts(mcp):
    await mcp.call_tool(
        "initialize_plan", {"case_name": "TEST-COUNTS-001"}
    )

    result = parse_tool_result(await mcp.call_tool("get_plan_summary", {}))
    counts = result["phase_counts"]
    assert counts.get("active", 0) == 1
    assert counts.get("pending", 0) == 7  # 8 default minus 1 active


# ───────────────────────────────────────────────────────────────────
# get_current_phase
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_current_phase(mcp):
    await mcp.call_tool(
        "initialize_plan", {"case_name": "TEST-CURRENT-001"}
    )

    result = parse_tool_result(await mcp.call_tool("get_current_phase", {}))
    assert result["name"] == "initial_triage"
    assert result["status"] == "active"
    assert "id" in result
    assert "goals" in result


# ───────────────────────────────────────────────────────────────────
# list_phases
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_phases(mcp):
    await mcp.call_tool(
        "initialize_plan", {"case_name": "TEST-LIST-001"}
    )

    result = parse_tool_result(await mcp.call_tool("list_phases", {}))
    assert isinstance(result, list)
    assert len(result) == 8
    for phase in result:
        assert "id" in phase
        assert "name" in phase
        assert "status" in phase
        assert "goal_count" in phase
        assert "open_goals" in phase


@pytest.mark.asyncio
async def test_list_phases_default_order(mcp):
    await mcp.call_tool(
        "initialize_plan", {"case_name": "TEST-ORDER-001"}
    )

    result = parse_tool_result(await mcp.call_tool("list_phases", {}))
    names = [p["name"] for p in result]
    expected = [
        "initial_triage", "initial_compromise", "execution",
        "persistence", "lateral_movement", "collection",
        "exfiltration", "impact",
    ]
    assert names == expected


# ───────────────────────────────────────────────────────────────────
# add_goal
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_goal(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-GOAL-001"}
        )
    )
    phase_id = plan["phases"][0]["id"]

    result = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {
                "phase_id": phase_id,
                "description": "Identify compromised hosts",
            },
        )
    )
    assert "id" in result
    assert result["description"] == "Identify compromised hosts"
    assert result["status"] == "open"


@pytest.mark.asyncio
async def test_add_goal_appears_in_current_phase(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-GOAL-APPEAR-001"}
        )
    )
    phase_id = plan["phases"][0]["id"]

    await mcp.call_tool(
        "add_goal",
        {"phase_id": phase_id, "description": "Enumerate user accounts"},
    )

    phase = parse_tool_result(await mcp.call_tool("get_current_phase", {}))
    assert len(phase["goals"]) == 1
    assert phase["goals"][0]["description"] == "Enumerate user accounts"


@pytest.mark.asyncio
async def test_add_multiple_goals(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-MULTI-GOAL-001"}
        )
    )
    phase_id = plan["phases"][0]["id"]

    for i in range(3):
        await mcp.call_tool(
            "add_goal",
            {"phase_id": phase_id, "description": f"Goal {i}"},
        )

    phase = parse_tool_result(await mcp.call_tool("get_current_phase", {}))
    assert len(phase["goals"]) == 3


# ───────────────────────────────────────────────────────────────────
# complete_goal
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_goal(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-COMPLETE-001"}
        )
    )
    phase_id = plan["phases"][0]["id"]

    goal = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": phase_id, "description": "Find entry point"},
        )
    )

    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {"goal_id": goal["id"], "notes": "Phishing email confirmed."},
        )
    )
    assert result["goal"]["status"] == "complete"
    assert result["goal"]["notes"] == "Phishing email confirmed."


@pytest.mark.asyncio
async def test_complete_goal_auto_advances_phase(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-ADVANCE-001"}
        )
    )
    phase_id = plan["phases"][0]["id"]

    goal = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": phase_id, "description": "Single goal"},
        )
    )

    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {"goal_id": goal["id"], "notes": "Done."},
        )
    )
    assert result["phase_advanced"] is True
    assert result["new_phase"] == "initial_compromise"


@pytest.mark.asyncio
async def test_complete_goal_no_advance_when_goals_remain(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-NO-ADVANCE-001"}
        )
    )
    phase_id = plan["phases"][0]["id"]

    goal1 = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": phase_id, "description": "Goal A"},
        )
    )
    await mcp.call_tool(
        "add_goal",
        {"phase_id": phase_id, "description": "Goal B"},
    )

    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {"goal_id": goal1["id"]},
        )
    )
    assert result["phase_advanced"] is False


@pytest.mark.asyncio
async def test_complete_already_complete_goal(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-IDEMPOTENT-001"}
        )
    )
    phase_id = plan["phases"][0]["id"]

    goal = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": phase_id, "description": "Already done"},
        )
    )

    await mcp.call_tool("complete_goal", {"goal_id": goal["id"]})

    # Complete again
    result = parse_tool_result(
        await mcp.call_tool("complete_goal", {"goal_id": goal["id"]})
    )
    assert result["phase_advanced"] is False
    assert "already complete" in result.get("message", "").lower() or result["goal"]["status"] == "complete"


# ───────────────────────────────────────────────────────────────────
# add_phase
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_phase_appended(mcp):
    await mcp.call_tool(
        "initialize_plan", {"case_name": "TEST-ADD-PHASE-001"}
    )

    result = parse_tool_result(
        await mcp.call_tool(
            "add_phase",
            {
                "name": "cloud_persistence",
                "description": "Check cloud-based persistence.",
            },
        )
    )
    assert result["name"] == "cloud_persistence"
    assert result["status"] == "pending"

    phases = parse_tool_result(await mcp.call_tool("list_phases", {}))
    assert phases[-1]["name"] == "cloud_persistence"


@pytest.mark.asyncio
async def test_add_phase_after_specific_phase(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-INSERT-PHASE-001"}
        )
    )
    first_phase_id = plan["phases"][0]["id"]

    await mcp.call_tool(
        "add_phase",
        {
            "name": "custom_inserted",
            "description": "Inserted after first phase.",
            "after_phase_id": first_phase_id,
        },
    )

    phases = parse_tool_result(await mcp.call_tool("list_phases", {}))
    names = [p["name"] for p in phases]
    idx = names.index("custom_inserted")
    assert idx == 1  # right after the first phase


# ───────────────────────────────────────────────────────────────────
# skip_phase
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skip_pending_phase(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-SKIP-001"}
        )
    )
    # Skip a pending phase (not the active first one)
    pending_phase_id = plan["phases"][1]["id"]

    result = parse_tool_result(
        await mcp.call_tool(
            "skip_phase",
            {
                "phase_id": pending_phase_id,
                "reason": "Not relevant to this investigation.",
            },
        )
    )
    assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_skip_active_phase_advances(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-SKIP-ACTIVE-001"}
        )
    )
    active_phase_id = plan["phases"][0]["id"]

    await mcp.call_tool(
        "skip_phase",
        {
            "phase_id": active_phase_id,
            "reason": "Skipping triage — going straight to compromise.",
        },
    )

    # The next phase should now be active
    current = parse_tool_result(await mcp.call_tool("get_current_phase", {}))
    assert current["name"] == "initial_compromise"
    assert current["status"] == "active"


@pytest.mark.asyncio
async def test_skip_phase_records_reason(mcp):
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan", {"case_name": "TEST-SKIP-REASON-001"}
        )
    )
    phase_id = plan["phases"][2]["id"]  # execution phase

    result = parse_tool_result(
        await mcp.call_tool(
            "skip_phase",
            {"phase_id": phase_id, "reason": "No execution artefacts found."},
        )
    )
    assert result["status"] == "skipped"


# ───────────────────────────────────────────────────────────────────
# Full lifecycle integration
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_plan_lifecycle(mcp):
    """Walk through a mini plan: init → add goals → complete → advance."""
    custom = [
        {"name": "phase_a", "description": "First phase"},
        {"name": "phase_b", "description": "Second phase"},
    ]
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan",
            {"case_name": "LIFECYCLE-001", "custom_phases": custom},
        )
    )
    phase_a_id = plan["phases"][0]["id"]

    # Add and complete a goal in phase_a
    goal = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": phase_a_id, "description": "Only goal"},
        )
    )
    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {"goal_id": goal["id"], "notes": "Completed"},
        )
    )
    assert result["phase_advanced"] is True
    assert result["new_phase"] == "phase_b"

    # Verify phase_b is now active
    current = parse_tool_result(await mcp.call_tool("get_current_phase", {}))
    assert current["name"] == "phase_b"
    assert current["status"] == "active"

    # Summary should reflect progress
    summary = parse_tool_result(await mcp.call_tool("get_plan_summary", {}))
    assert summary["current_phase"] == "phase_b"
    assert summary["phase_counts"]["complete"] == 1
