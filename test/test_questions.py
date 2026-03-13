"""
Tests for question/answer tools: submit_question, get_next_question,
submit_answer, get_question, check_children.
"""

import pytest
from conftest import parse_tool_result


# ───────────────────────────────────────────────────────────────────
# submit_question
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_question_success(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Was cmd.exe executed between 10:00 and 11:00?",
                "hypothesis": "Attacker used command shell",
                "evidence_hints": ["Prefetch"],
                "priority": 1,
            },
        )
    )
    assert "question_id" in result
    assert result["assigned_role"] == "parser:Prefetch"
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_submit_question_default_priority(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Any evidence of lateral movement?",
                "hypothesis": "Lateral movement via RDP",
                "evidence_hints": ["EVTX"],
            },
        )
    )
    assert "question_id" in result
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_submit_question_empty_hints_rejected(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Some question",
                "hypothesis": "Some hypothesis",
                "evidence_hints": [],
            },
        )
    )
    assert result["success"] is False
    assert "at least one" in result["error"]
    assert "valid_artefacts" in result


@pytest.mark.asyncio
async def test_submit_question_invalid_artefact_rejected(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Some question",
                "hypothesis": "Some hypothesis",
                "evidence_hints": ["InvalidArtefact"],
            },
        )
    )
    assert result["success"] is False
    assert "Unknown artefact" in result["error"]
    assert "valid_artefacts" in result


@pytest.mark.asyncio
async def test_submit_question_with_goal_id(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Was powershell.exe used?",
                "hypothesis": "LOLBin usage",
                "evidence_hints": ["Amcache"],
                "goal_id": "test-goal-123",
            },
        )
    )
    assert result["goal_id"] == "test-goal-123"


@pytest.mark.asyncio
async def test_submit_question_all_valid_artefacts(mcp):
    artefacts = [
        "Prefetch", "Amcache", "AppCompatCache", "EVTX",
        "MFT", "UsnJrnl", "Registry", "ShellBags",
        "JumpLists", "LNK", "RecycleBin", "SRUM",
        "RecentFileCache", "Defender",
    ]
    for art in artefacts:
        result = parse_tool_result(
            await mcp.call_tool(
                "submit_question",
                {
                    "text": f"Test question for {art}",
                    "hypothesis": "Validation test",
                    "evidence_hints": [art],
                },
            )
        )
        assert "question_id" in result, f"Failed for artefact: {art}"
        assert result["assigned_role"] == f"parser:{art}"


# ───────────────────────────────────────────────────────────────────
# get_next_question
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_next_question_empty_queue(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "get_next_question",
            {"agent_role": "parser:NonExistentArtefact"},
        )
    )
    assert result["empty"] is True


@pytest.mark.asyncio
async def test_get_next_question_claims_pending(mcp):
    # Submit a question targeted at a unique artefact role
    submit_result = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Claim test question",
                "hypothesis": "Testing claim",
                "evidence_hints": ["LNK"],
                "priority": 1,
            },
        )
    )
    question_id = submit_result["question_id"]

    # Claim it
    claim_result = parse_tool_result(
        await mcp.call_tool(
            "get_next_question", {"agent_role": "parser:LNK"}
        )
    )
    assert claim_result.get("empty") is not True
    assert claim_result["question_id"] == question_id
    assert claim_result["status"] == "in_progress"


@pytest.mark.asyncio
async def test_get_next_question_returns_question_fields(mcp):
    await mcp.call_tool(
        "submit_question",
        {
            "text": "Field check question",
            "hypothesis": "Field check hypothesis",
            "evidence_hints": ["RecycleBin"],
            "priority": 2,
        },
    )

    result = parse_tool_result(
        await mcp.call_tool(
            "get_next_question", {"agent_role": "parser:RecycleBin"}
        )
    )
    assert "question_id" in result
    assert "text" in result
    assert "hypothesis" in result
    assert "evidence_hints" in result
    assert "priority" in result
    assert "assigned_role" in result


# ───────────────────────────────────────────────────────────────────
# submit_answer
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_answer_success(mcp):
    # Submit and claim
    submit_result = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Answer test question",
                "hypothesis": "Testing answers",
                "evidence_hints": ["SRUM"],
            },
        )
    )
    q_id = submit_result["question_id"]

    await mcp.call_tool("get_next_question", {"agent_role": "parser:SRUM"})

    # Answer
    answer_result = parse_tool_result(
        await mcp.call_tool(
            "submit_answer",
            {
                "question_id": q_id,
                "answer": "Yes, network activity detected.",
                "confirmed": True,
                "evidence_refs": ["srum_table:row_42"],
                "iocs": [{"type": "ip", "value": "10.0.0.1"}],
            },
        )
    )
    assert answer_result["success"] is True
    assert answer_result["question_id"] == q_id
    assert answer_result["status"] == "answered"


@pytest.mark.asyncio
async def test_submit_answer_with_parent_id(mcp):
    submit_result = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Parent tracking test",
                "hypothesis": "Test",
                "evidence_hints": ["MFT"],
                "goal_id": "goal-parent-test",
            },
        )
    )
    q_id = submit_result["question_id"]

    await mcp.call_tool("get_next_question", {"agent_role": "parser:MFT"})

    answer_result = parse_tool_result(
        await mcp.call_tool(
            "submit_answer",
            {
                "question_id": q_id,
                "answer": "No anomalies found.",
                "confirmed": False,
                "evidence_refs": [],
                "iocs": [],
            },
        )
    )
    assert answer_result["parent_id"] == "goal-parent-test"


# ───────────────────────────────────────────────────────────────────
# get_question
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_question_found(mcp):
    submit_result = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Retrieval test",
                "hypothesis": "Test get_question",
                "evidence_hints": ["Registry"],
            },
        )
    )
    q_id = submit_result["question_id"]

    result = parse_tool_result(
        await mcp.call_tool("get_question", {"question_id": q_id})
    )
    assert result["found"] is True
    assert result["question_id"] == q_id
    assert result["text"] == "Retrieval test"


@pytest.mark.asyncio
async def test_get_question_not_found(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "get_question", {"question_id": "does_not_exist"}
        )
    )
    assert result["found"] is False


@pytest.mark.asyncio
async def test_get_question_shows_answer_after_answering(mcp):
    submit_result = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Answer visibility test",
                "hypothesis": "Test",
                "evidence_hints": ["ShellBags"],
            },
        )
    )
    q_id = submit_result["question_id"]

    await mcp.call_tool(
        "get_next_question", {"agent_role": "parser:ShellBags"}
    )
    await mcp.call_tool(
        "submit_answer",
        {
            "question_id": q_id,
            "answer": "Confirmed shell bag entries.",
            "confirmed": True,
            "evidence_refs": ["shellbags_output.csv"],
            "iocs": [],
        },
    )

    result = parse_tool_result(
        await mcp.call_tool("get_question", {"question_id": q_id})
    )
    assert result["status"] == "answered"
    assert result["answer"] == "Confirmed shell bag entries."
    assert result["answer_detail"]["confirmed"] is True


# ───────────────────────────────────────────────────────────────────
# check_children
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_children_no_children(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "check_children", {"parent_id": "nonexistent_parent"}
        )
    )
    assert result["ready"] is False
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_check_children_pending(mcp):
    parent_id = "check-children-test-1"
    await mcp.call_tool(
        "submit_question",
        {
            "text": "Child question 1",
            "hypothesis": "Test",
            "evidence_hints": ["Prefetch"],
            "goal_id": parent_id,
        },
    )
    await mcp.call_tool(
        "submit_question",
        {
            "text": "Child question 2",
            "hypothesis": "Test",
            "evidence_hints": ["Amcache"],
            "goal_id": parent_id,
        },
    )

    result = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": parent_id})
    )
    assert result["ready"] is False
    assert result["total"] == 2
    assert result["pending"] == 2


@pytest.mark.asyncio
async def test_check_children_all_answered(mcp):
    parent_id = "check-children-test-2"

    # Submit two questions under the same parent
    q1 = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "All-answered child 1",
                "hypothesis": "Test",
                "evidence_hints": ["Defender"],
                "goal_id": parent_id,
            },
        )
    )
    q2 = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "All-answered child 2",
                "hypothesis": "Test",
                "evidence_hints": ["UsnJrnl"],
                "goal_id": parent_id,
            },
        )
    )

    # Claim and answer both
    await mcp.call_tool(
        "get_next_question", {"agent_role": "parser:Defender"}
    )
    await mcp.call_tool(
        "submit_answer",
        {
            "question_id": q1["question_id"],
            "answer": "No threats.",
            "confirmed": False,
            "evidence_refs": [],
            "iocs": [],
        },
    )

    await mcp.call_tool(
        "get_next_question", {"agent_role": "parser:UsnJrnl"}
    )
    await mcp.call_tool(
        "submit_answer",
        {
            "question_id": q2["question_id"],
            "answer": "No journal anomalies.",
            "confirmed": False,
            "evidence_refs": [],
            "iocs": [],
        },
    )

    result = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": parent_id})
    )
    assert result["ready"] is True
    assert result["answered"] == 2
    assert result["pending"] == 0


@pytest.mark.asyncio
async def test_check_children_partial(mcp):
    parent_id = "check-children-test-3"

    q1 = parse_tool_result(
        await mcp.call_tool(
            "submit_question",
            {
                "text": "Partial child 1",
                "hypothesis": "Test",
                "evidence_hints": ["AppCompatCache"],
                "goal_id": parent_id,
            },
        )
    )
    await mcp.call_tool(
        "submit_question",
        {
            "text": "Partial child 2",
            "hypothesis": "Test",
            "evidence_hints": ["JumpLists"],
            "goal_id": parent_id,
        },
    )

    # Only answer the first
    await mcp.call_tool(
        "get_next_question", {"agent_role": "parser:AppCompatCache"}
    )
    await mcp.call_tool(
        "submit_answer",
        {
            "question_id": q1["question_id"],
            "answer": "Found entries.",
            "confirmed": True,
            "evidence_refs": ["appcompat.csv"],
            "iocs": [],
        },
    )

    result = parse_tool_result(
        await mcp.call_tool("check_children", {"parent_id": parent_id})
    )
    assert result["ready"] is False
    assert result["answered"] == 1
    assert result["pending"] == 1
