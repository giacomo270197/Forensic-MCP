"""
Tests for findings tools: add_timeline_entry, write_finding, summarise_findings.
"""

import pytest
from conftest import parse_tool_result


# ───────────────────────────────────────────────────────────────────
# add_timeline_entry
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_timeline_entry_success(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "add_timeline_entry",
            {
                "time": "2024-03-15T14:32:01Z",
                "event": "Suspicious process launched",
                "evidence_source": "Prefetch",
                "relevance": "Indicates malware execution",
            },
        )
    )
    assert result["status"] == "ok"
    assert "timeline_path" in result


@pytest.mark.asyncio
async def test_add_timeline_entry_returns_entry(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "add_timeline_entry",
            {
                "time": "2024-01-01T00:00:00Z",
                "event": "Test event",
                "evidence_source": "Test source",
                "relevance": "Test relevance",
            },
        )
    )
    entry = result["entry"]
    assert entry["time"] == "2024-01-01T00:00:00Z"
    assert entry["event"] == "Test event"
    assert entry["evidence_source"] == "Test source"
    assert entry["relevance"] == "Test relevance"


@pytest.mark.asyncio
async def test_add_multiple_timeline_entries(mcp):
    for i in range(3):
        result = parse_tool_result(
            await mcp.call_tool(
                "add_timeline_entry",
                {
                    "time": f"2024-03-15T10:0{i}:00Z",
                    "event": f"Event {i}",
                    "evidence_source": "MFT",
                    "relevance": f"Relevance {i}",
                },
            )
        )
        assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_add_timeline_entry_path_contains_timeline(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "add_timeline_entry",
            {
                "time": "2024-06-01T12:00:00Z",
                "event": "Path check",
                "evidence_source": "EVTX",
                "relevance": "Verify path",
            },
        )
    )
    assert "timeline.csv" in result["timeline_path"]


# ───────────────────────────────────────────────────────────────────
# write_finding
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_finding_success(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "write_finding",
            {
                "title": "Suspicious DLL sideloading",
                "content": "Found evidence of DLL sideloading via calc.exe.",
                "severity": "high",
            },
        )
    )
    assert result["status"] == "ok"
    assert "note_path" in result
    assert result["severity"] == "high"


@pytest.mark.asyncio
async def test_write_finding_default_severity(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "write_finding",
            {
                "title": "Minor observation",
                "content": "Nothing too alarming.",
            },
        )
    )
    assert result["status"] == "ok"
    assert result["severity"] == "medium"


@pytest.mark.asyncio
async def test_write_finding_returns_title(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "write_finding",
            {
                "title": "Title Echo Test",
                "content": "Body content.",
                "severity": "low",
            },
        )
    )
    assert result["title"] == "Title Echo Test"


@pytest.mark.asyncio
async def test_write_finding_path_is_markdown(mcp):
    result = parse_tool_result(
        await mcp.call_tool(
            "write_finding",
            {
                "title": "Format check",
                "content": "Check file extension.",
                "severity": "critical",
            },
        )
    )
    assert result["note_path"].endswith(".md")


@pytest.mark.asyncio
async def test_write_finding_all_severities(mcp):
    for sev in ("low", "medium", "high", "critical"):
        result = parse_tool_result(
            await mcp.call_tool(
                "write_finding",
                {
                    "title": f"Severity {sev}",
                    "content": f"Testing {sev} severity.",
                    "severity": sev,
                },
            )
        )
        assert result["status"] == "ok"
        assert result["severity"] == sev


# ───────────────────────────────────────────────────────────────────
# summarise_findings
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summarise_findings_with_data(mcp):
    # Seed at least one timeline entry and one finding
    await mcp.call_tool(
        "add_timeline_entry",
        {
            "time": "2024-03-15T09:00:00Z",
            "event": "Summarise seed event",
            "evidence_source": "Amcache",
            "relevance": "Needed for summary test",
        },
    )
    await mcp.call_tool(
        "write_finding",
        {
            "title": "Summarise seed finding",
            "content": "Content for summary test.",
            "severity": "low",
        },
    )

    result = parse_tool_result(await mcp.call_tool("summarise_findings", {}))
    assert result["status"] == "ok"
    assert "report_path" in result
    assert "report" in result
    assert "report.md" in result["report_path"]


@pytest.mark.asyncio
async def test_summarise_findings_report_has_timeline_table(mcp):
    await mcp.call_tool(
        "add_timeline_entry",
        {
            "time": "2024-07-01T08:00:00Z",
            "event": "Table check event",
            "evidence_source": "Registry",
            "relevance": "Verify table rendering",
        },
    )

    result = parse_tool_result(await mcp.call_tool("summarise_findings", {}))
    report = result["report"]
    assert "## Timeline" in report
    assert "| Time |" in report


@pytest.mark.asyncio
async def test_summarise_findings_report_has_notes_section(mcp):
    await mcp.call_tool(
        "write_finding",
        {
            "title": "Notes section test",
            "content": "Should appear in report.",
        },
    )

    result = parse_tool_result(await mcp.call_tool("summarise_findings", {}))
    assert "## Analyst Notes" in result["report"]
