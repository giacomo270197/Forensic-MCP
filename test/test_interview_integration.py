"""
Integration test: interviewer agent ↔ answering agents.

Simulates the full orchestration loop:
1. Interviewer initialises a plan and adds goals
2. Interviewer submits high-level questions linked to goals
3. Parser agents claim and answer their assigned questions
4. Interviewer checks children readiness and completes goals
5. Phase auto-advances once all goals are closed
6. Findings and timeline entries are written along the way
7. Final report is compiled via summarise_findings
"""

import pytest
from conftest import parse_tool_result


async def _tool_available(mcp, tool_name: str) -> bool:
    tools = await mcp.list_tools()
    return any(t.name == tool_name for t in tools)


@pytest.fixture(autouse=True)
async def _skip_if_unavailable(mcp):
    for tool in ("initialize_plan", "submit_question", "add_timeline_entry"):
        if not await _tool_available(mcp, tool):
            pytest.skip(f"Tool '{tool}' not registered on server.")


# ───────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────


async def interviewer_submit_question(mcp, text, hypothesis, hints, goal_id, priority=3):
    """Interviewer submits a question targeting a goal."""
    return parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": text,
                "hypothesis": hypothesis,
                "evidence_hints": hints,
                "goal_id": goal_id,
                "priority": priority,
            },
        )
    )


async def parser_claim_and_answer(mcp, role, answer, confirmed, evidence_refs=None, iocs=None):
    """Parser agent claims the next question for its role and answers it."""
    claim = parse_tool_result(
        await mcp.call_tool("get_next_question", {"agent_role": role})
    )
    assert claim.get("empty") is not True, f"No pending question for {role}"

    result = parse_tool_result(
        await mcp.call_tool(
            "submit_answer",
            {
                "question_id": claim["question_id"],
                "answer": answer,
                "confirmed": confirmed,
                "evidence_refs": evidence_refs or [],
                "iocs": iocs or [],
            },
        )
    )
    assert result["success"] is True
    assert result["status"] == "answered"
    return claim["question_id"]


# ───────────────────────────────────────────────────────────────────
# Single-goal, single-question round-trip
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_question_round_trip(mcp):
    """Interviewer asks one question, parser answers, goal completes."""
    # --- Interviewer: set up plan ---
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan",
            {
                "case_name": "INTEG-SINGLE-001",
                "custom_phases": [
                    {"name": "triage", "description": "Quick triage"},
                ],
            },
        )
    )
    phase_id = plan["phases"][0]["id"]

    goal = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": phase_id, "description": "Determine if cmd.exe ran"},
        )
    )
    goal_id = goal["id"]

    # --- Interviewer: submit question ---
    q = await interviewer_submit_question(
        mcp,
        text="Is there a Prefetch file for cmd.exe?",
        hypothesis="Attacker used cmd.exe",
        hints=["Prefetch"],
        goal_id=goal_id,
        priority=1,
    )
    assert q["assigned_role"] == "parser:Prefetch"

    # --- Parser:Prefetch answers ---
    await parser_claim_and_answer(
        mcp,
        role="parser:Prefetch",
        answer="Yes, CMD.EXE-*.pf found with 12 run count, last run 2026-03-10T14:22:00.",
        confirmed=True,
        evidence_refs=["prefetch/CMD.EXE-4A81B364.pf"],
    )

    # --- Interviewer: verify children ready, complete goal ---
    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal_id})
    )
    assert children["ready"] is True
    assert children["answered"] == 1

    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {"goal_id": goal_id, "notes": "cmd.exe confirmed via Prefetch."},
        )
    )
    assert result["goal"]["status"] == "complete"


# ───────────────────────────────────────────────────────────────────
# Multi-parser fan-out: one goal, multiple evidence sources
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_parser_fan_out(mcp):
    """Interviewer fans out one goal across Prefetch, Amcache, and EVTX parsers."""
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan",
            {
                "case_name": "INTEG-FANOUT-001",
                "custom_phases": [
                    {"name": "execution_check", "description": "Verify execution"},
                ],
            },
        )
    )
    phase_id = plan["phases"][0]["id"]

    goal = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": phase_id, "description": "Confirm powershell.exe execution"},
        )
    )
    goal_id = goal["id"]

    # --- Interviewer: fan out questions to three parsers ---
    await interviewer_submit_question(
        mcp,
        text="Check Prefetch for powershell.exe",
        hypothesis="PowerShell execution",
        hints=["Prefetch"],
        goal_id=goal_id,
    )
    await interviewer_submit_question(
        mcp,
        text="Check Amcache for powershell.exe entries",
        hypothesis="PowerShell execution",
        hints=["Amcache"],
        goal_id=goal_id,
    )
    await interviewer_submit_question(
        mcp,
        text="Check event logs for process creation (4688) of powershell.exe",
        hypothesis="PowerShell execution",
        hints=["EVTX"],
        goal_id=goal_id,
    )

    # Not ready yet — nothing answered
    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal_id})
    )
    assert children["ready"] is False
    assert children["total"] == 3
    assert children["pending"] == 3

    # --- Parsers answer one by one ---
    await parser_claim_and_answer(
        mcp,
        role="parser:Prefetch",
        answer="POWERSHELL.EXE-*.pf found, 5 executions, last 2026-03-11T08:15:00.",
        confirmed=True,
        evidence_refs=["prefetch/POWERSHELL.EXE-022A1004.pf"],
    )

    # Still not ready (1/3)
    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal_id})
    )
    assert children["ready"] is False
    assert children["answered"] == 1
    assert children["pending"] == 2

    await parser_claim_and_answer(
        mcp,
        role="parser:Amcache",
        answer="Amcache entry for PowerShell v5.1, SHA1 matches known-good.",
        confirmed=True,
        evidence_refs=["amcache/Amcache.hve"],
    )

    await parser_claim_and_answer(
        mcp,
        role="parser:EVTX",
        answer="Event 4688: powershell.exe spawned by explorer.exe at 2026-03-11T08:14:58.",
        confirmed=True,
        evidence_refs=["evtx/Security.evtx"],
        iocs=[{"type": "process", "value": "powershell.exe"}],
    )

    # Now ready
    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal_id})
    )
    assert children["ready"] is True
    assert children["answered"] == 3

    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {
                "goal_id": goal_id,
                "notes": "PowerShell execution confirmed across Prefetch, Amcache, and EVTX.",
            },
        )
    )
    assert result["goal"]["status"] == "complete"


# ───────────────────────────────────────────────────────────────────
# Multi-phase lifecycle with findings and timeline
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_interview_lifecycle(mcp):
    """
    End-to-end: two phases, multiple goals, questions, answers,
    timeline entries, findings, and a final report.
    """
    # === Phase setup ===
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan",
            {
                "case_name": "INTEG-FULL-001",
                "custom_phases": [
                    {"name": "triage", "description": "Initial triage"},
                    {"name": "deep_dive", "description": "Deep investigation"},
                ],
            },
        )
    )
    triage_id = plan["phases"][0]["id"]

    # === Phase 1: Triage ===
    goal_exec = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": triage_id, "description": "Identify suspicious executables"},
        )
    )
    goal_network = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": triage_id, "description": "Check for network anomalies"},
        )
    )

    # Interviewer asks about execution
    await interviewer_submit_question(
        mcp,
        text="Any unknown executables in Prefetch?",
        hypothesis="Malware execution",
        hints=["Prefetch"],
        goal_id=goal_exec["id"],
        priority=1,
    )
    await interviewer_submit_question(
        mcp,
        text="Check Amcache for unsigned binaries",
        hypothesis="Malware execution",
        hints=["Amcache"],
        goal_id=goal_exec["id"],
        priority=2,
    )

    # Interviewer asks about network
    await interviewer_submit_question(
        mcp,
        text="Any unusual network connections in SRUM?",
        hypothesis="Data exfiltration",
        hints=["SRUM"],
        goal_id=goal_network["id"],
    )

    # --- Parsers answer ---
    await parser_claim_and_answer(
        mcp,
        role="parser:Prefetch",
        answer="Found MALWARE.EXE-*.pf, 1 execution at 2026-03-10T03:00:00.",
        confirmed=True,
        evidence_refs=["prefetch/MALWARE.EXE-ABC12345.pf"],
        iocs=[{"type": "filename", "value": "MALWARE.EXE"}],
    )

    # Parser writes a timeline entry (simulating subagent behaviour)
    await mcp.call_tool(
        "add_timeline_entry",
        {
            "time": "2026-03-10T03:00:00",
            "event": "MALWARE.EXE first execution (Prefetch)",
            "evidence_source": "Prefetch",
            "relevance": "Possible initial malware execution",
        },
    )

    await parser_claim_and_answer(
        mcp,
        role="parser:Amcache",
        answer="MALWARE.EXE found in Amcache, unsigned, no publisher.",
        confirmed=True,
        evidence_refs=["amcache/Amcache.hve"],
        iocs=[{"type": "sha1", "value": "aabbccdd11223344"}],
    )

    # Parser writes a finding
    await mcp.call_tool(
        "write_finding",
        {
            "title": "Unsigned binary in Amcache",
            "content": "MALWARE.EXE appears in Amcache with no digital signature.",
            "severity": "high",
        },
    )

    # Complete execution goal
    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal_exec["id"]})
    )
    assert children["ready"] is True

    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {
                "goal_id": goal_exec["id"],
                "notes": "MALWARE.EXE confirmed via Prefetch and Amcache.",
            },
        )
    )
    assert result["goal"]["status"] == "complete"
    assert result["phase_advanced"] is False  # network goal still open

    # Answer network question
    await parser_claim_and_answer(
        mcp,
        role="parser:SRUM",
        answer="Spike of 500 MB outbound to 185.220.101.42 at 2026-03-10T04:00:00.",
        confirmed=True,
        evidence_refs=["srum/SRUDB.dat"],
        iocs=[{"type": "ip", "value": "185.220.101.42"}],
    )

    await mcp.call_tool(
        "add_timeline_entry",
        {
            "time": "2026-03-10T04:00:00",
            "event": "500 MB exfiltration to 185.220.101.42 (SRUM)",
            "evidence_source": "SRUM",
            "relevance": "Possible data exfiltration",
        },
    )

    await mcp.call_tool(
        "write_finding",
        {
            "title": "Large outbound transfer to Tor exit node",
            "content": "SRUM shows 500 MB sent to 185.220.101.42 (known Tor exit).",
            "severity": "critical",
        },
    )

    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal_network["id"]})
    )
    assert children["ready"] is True

    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {
                "goal_id": goal_network["id"],
                "notes": "500 MB exfil to Tor exit node confirmed via SRUM.",
            },
        )
    )
    assert result["goal"]["status"] == "complete"
    assert result["phase_advanced"] is True
    assert result["new_phase"] == "deep_dive"

    # === Phase 2: Deep dive ===
    current = parse_tool_result(await mcp.call_tool("get_current_phase", {}))
    assert current["name"] == "deep_dive"
    assert current["status"] == "active"
    deep_dive_id = current["id"]

    goal_persist = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": deep_dive_id, "description": "Check for persistence mechanisms"},
        )
    )

    await interviewer_submit_question(
        mcp,
        text="Any suspicious registry Run keys?",
        hypothesis="Persistence via registry",
        hints=["Registry"],
        goal_id=goal_persist["id"],
    )

    await parser_claim_and_answer(
        mcp,
        role="parser:Registry",
        answer="HKCU\\...\\Run contains 'WindowsUpdate' → C:\\Temp\\MALWARE.EXE.",
        confirmed=True,
        evidence_refs=["registry/NTUSER.DAT"],
        iocs=[{"type": "regkey", "value": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\WindowsUpdate"}],
    )

    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal_persist["id"]})
    )
    assert children["ready"] is True

    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {
                "goal_id": goal_persist["id"],
                "notes": "Registry Run key persistence found.",
            },
        )
    )
    assert result["goal"]["status"] == "complete"

    # === Final summary ===
    summary = parse_tool_result(await mcp.call_tool("get_plan_summary", {}))
    assert summary["phase_counts"]["complete"] == 2
    assert summary["closed_goals"] >= 3

    report = parse_tool_result(await mcp.call_tool("summarise_findings", {}))
    assert report["status"] == "ok"
    assert "report_path" in report


# ───────────────────────────────────────────────────────────────────
# Negative-result interview: parser finds nothing
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_interview_with_negative_findings(mcp):
    """Parser answers 'not found' — interviewer still completes the goal."""
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan",
            {
                "case_name": "INTEG-NEG-001",
                "custom_phases": [
                    {"name": "check", "description": "Evidence check"},
                ],
            },
        )
    )
    phase_id = plan["phases"][0]["id"]

    goal = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": phase_id, "description": "Look for lateral movement in logs"},
        )
    )

    await interviewer_submit_question(
        mcp,
        text="Any RDP logon events (4624 type 10) in Security.evtx?",
        hypothesis="Lateral movement via RDP",
        hints=["EVTX"],
        goal_id=goal["id"],
    )

    await parser_claim_and_answer(
        mcp,
        role="parser:EVTX",
        answer="No type-10 logon events found in the timeframe.",
        confirmed=False,
        evidence_refs=["evtx/Security.evtx"],
    )

    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal["id"]})
    )
    assert children["ready"] is True

    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {"goal_id": goal["id"], "notes": "No RDP lateral movement found."},
        )
    )
    assert result["goal"]["status"] == "complete"


# ───────────────────────────────────────────────────────────────────
# Interviewer asks follow-up questions after initial answers
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_interview_follow_up_questions(mcp):
    """Interviewer reviews first answer, then asks a follow-up under the same goal."""
    plan = parse_tool_result(
        await mcp.call_tool(
            "initialize_plan",
            {
                "case_name": "INTEG-FOLLOWUP-001",
                "custom_phases": [
                    {"name": "investigate", "description": "Investigation"},
                ],
            },
        )
    )
    phase_id = plan["phases"][0]["id"]

    goal = parse_tool_result(
        await mcp.call_tool(
            "add_goal",
            {"phase_id": phase_id, "description": "Investigate suspicious DLL"},
        )
    )
    goal_id = goal["id"]

    # Round 1: initial question
    await interviewer_submit_question(
        mcp,
        text="Any DLL side-loading in Amcache?",
        hypothesis="DLL hijack",
        hints=["Amcache"],
        goal_id=goal_id,
    )

    await parser_claim_and_answer(
        mcp,
        role="parser:Amcache",
        answer="Suspicious unsigned version.dll loaded by legitimate app at 2026-03-10T09:00.",
        confirmed=True,
        evidence_refs=["amcache/Amcache.hve"],
        iocs=[{"type": "filename", "value": "version.dll"}],
    )

    # Check — answered but interviewer wants more detail
    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal_id})
    )
    assert children["ready"] is True
    assert children["answered"] == 1

    # Round 2: follow-up — check MFT for the same DLL
    await interviewer_submit_question(
        mcp,
        text="Find version.dll creation timestamp in MFT",
        hypothesis="DLL dropped before side-load",
        hints=["MFT"],
        goal_id=goal_id,
    )

    # Now not ready again (new pending question)
    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal_id})
    )
    assert children["ready"] is False
    assert children["total"] == 2
    assert children["pending"] == 1

    await parser_claim_and_answer(
        mcp,
        role="parser:MFT",
        answer="version.dll created 2026-03-10T08:55:00, 5 min before Amcache entry.",
        confirmed=True,
        evidence_refs=["mft/$MFT"],
    )

    children = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": goal_id})
    )
    assert children["ready"] is True
    assert children["answered"] == 2

    result = parse_tool_result(
        await mcp.call_tool(
            "complete_goal",
            {
                "goal_id": goal_id,
                "notes": "DLL side-loading confirmed: version.dll dropped at 08:55, loaded at 09:00.",
            },
        )
    )
    assert result["goal"]["status"] == "complete"
