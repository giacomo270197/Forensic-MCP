"""
Unit tests for mcp_tools._state — InvestigationState.

These are pure unit tests that do not require the MCP server to be running.
They exercise the state machine directly: hypotheses, tasks, queue control,
task timeouts, pending review, and full state dumps.
"""

import json
import os
import sys
import time

import pytest

# Allow imports from the src directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcp_tools._state import (
    InvestigationState,
    HypothesisStatus,
    TaskAssessment,
    TaskStatus,
)


@pytest.fixture
def state(tmp_path):
    """Fresh InvestigationState backed by a temp file."""
    import mcp_tools._state as mod

    original = mod.STATE_FILE
    mod.STATE_FILE = str(tmp_path / "state.json")
    s = InvestigationState()
    yield s
    mod.STATE_FILE = original


# ───────────────────────────────────────────────────────────────────
# Queue control
# ───────────────────────────────────────────────────────────────────


def test_queue_starts_closed(state):
    assert state.queue_open is False


def test_open_and_close_queue(state):
    state.set_queue_open(True)
    assert state.queue_open is True
    state.set_queue_open(False)
    assert state.queue_open is False


# ───────────────────────────────────────────────────────────────────
# Hypothesis CRUD
# ───────────────────────────────────────────────────────────────────


def test_create_hypothesis(state):
    h = state.create_hypothesis("q1", "Attacker used RDP")
    assert h.question_id == "q1"
    assert h.statement == "Attacker used RDP"
    assert h.status == HypothesisStatus.OPEN


def test_update_hypothesis_statement(state):
    h = state.create_hypothesis("q1", "Original claim")
    h2 = state.update_hypothesis(h.id, new_statement="Revised claim")
    assert h2.statement == "Revised claim"
    assert h2.status == HypothesisStatus.OPEN


def test_update_hypothesis_status(state):
    h = state.create_hypothesis("q1", "Test")
    state.update_hypothesis(h.id, new_status="confirmed")
    h2 = state.update_hypothesis(h.id)
    assert h2.status == "confirmed"


def test_update_hypothesis_invalid_status(state):
    h = state.create_hypothesis("q1", "Test")
    with pytest.raises(ValueError, match="Invalid status"):
        state.update_hypothesis(h.id, new_status="maybe")


def test_update_nonexistent_hypothesis(state):
    with pytest.raises(ValueError, match="not found"):
        state.update_hypothesis("no-such-id", new_statement="x")


def test_list_hypotheses_all(state):
    state.create_hypothesis("q1", "H1")
    state.create_hypothesis("q2", "H2")
    assert len(state.list_hypotheses()) == 2


def test_list_hypotheses_filtered(state):
    state.create_hypothesis("q1", "H1")
    state.create_hypothesis("q2", "H2")
    state.create_hypothesis("q1", "H3")
    assert len(state.list_hypotheses(question_id="q1")) == 2
    assert len(state.list_hypotheses(question_id="q2")) == 1


# ───────────────────────────────────────────────────────────────────
# Task CRUD
# ───────────────────────────────────────────────────────────────────


def test_create_task(state):
    h = state.create_hypothesis("q1", "Test")
    t = state.create_task(h.id, "Check EVTX for 4624", task_type="evtx")
    assert t.hypothesis_id == h.id
    assert t.description == "Check EVTX for 4624"
    assert t.task_type == "evtx"
    assert t.status == TaskStatus.PENDING


def test_create_task_invalid_hypothesis(state):
    with pytest.raises(ValueError, match="not found"):
        state.create_task("bad-id", "Do something")


def test_create_task_default_type(state):
    h = state.create_hypothesis("q1", "Test")
    t = state.create_task(h.id, "General task")
    assert t.task_type == "general"


# ───────────────────────────────────────────────────────────────────
# claim_task
# ───────────────────────────────────────────────────────────────────


def test_claim_task_returns_none_when_empty(state):
    task, queue_open = state.claim_task("worker-1")
    assert task is None
    assert queue_open is False


def test_claim_task_returns_pending_task(state):
    h = state.create_hypothesis("q1", "Test")
    t = state.create_task(h.id, "Do something", task_type="general")
    state.set_queue_open(True)

    claimed, queue_open = state.claim_task("worker-1", task_type="general")
    assert claimed is not None
    assert claimed.id == t.id
    assert claimed.status == TaskStatus.CLAIMED
    assert claimed.claimed_by == "worker-1"
    assert queue_open is True


def test_claim_task_filters_by_type(state):
    h = state.create_hypothesis("q1", "Test")
    state.create_task(h.id, "EVTX task", task_type="evtx")
    state.create_task(h.id, "Registry task", task_type="registry")

    claimed, _ = state.claim_task("worker-1", task_type="registry")
    assert claimed is not None
    assert claimed.task_type == "registry"


def test_claim_task_skips_already_claimed(state):
    h = state.create_hypothesis("q1", "Test")
    state.create_task(h.id, "Task A", task_type="general")
    state.create_task(h.id, "Task B", task_type="general")

    state.claim_task("worker-1", task_type="general")
    claimed, _ = state.claim_task("worker-2", task_type="general")
    assert claimed is not None
    assert claimed.description == "Task B"


def test_claim_task_no_match_returns_none(state):
    h = state.create_hypothesis("q1", "Test")
    state.create_task(h.id, "EVTX task", task_type="evtx")

    claimed, _ = state.claim_task("worker-1", task_type="registry")
    assert claimed is None


# ───────────────────────────────────────────────────────────────────
# complete_task
# ───────────────────────────────────────────────────────────────────


def test_complete_task_supports(state):
    h = state.create_hypothesis("q1", "Test hypothesis")
    t = state.create_task(h.id, "Check something")
    state.claim_task("worker-1", task_type="general")

    done = state.complete_task(
        t.id,
        found=True,
        summary="Found evidence",
        evidence=["event_id:4624", "user:admin"],
        assessment="supports",
    )
    assert done.status == TaskStatus.DONE
    assert done.result == {
        "found": True,
        "summary": "Found evidence",
        "evidence": ["event_id:4624", "user:admin"],
    }

    # Hypothesis should have this task in supporting list
    hs = state.list_hypotheses()
    assert t.id in hs[0].supporting_task_ids


def test_complete_task_refutes(state):
    h = state.create_hypothesis("q1", "Test")
    t = state.create_task(h.id, "Check something")
    state.claim_task("worker-1", task_type="general")

    state.complete_task(t.id, found=False, summary="Not found",
                        evidence=[], assessment="refutes")
    hs = state.list_hypotheses()
    assert t.id in hs[0].refuting_task_ids


def test_complete_task_neutral(state):
    h = state.create_hypothesis("q1", "Test")
    t = state.create_task(h.id, "Check something")
    state.claim_task("worker-1", task_type="general")

    state.complete_task(t.id, found=False, summary="Inconclusive",
                        evidence=[], assessment="neutral")
    hs = state.list_hypotheses()
    assert t.id not in hs[0].supporting_task_ids
    assert t.id not in hs[0].refuting_task_ids


def test_complete_task_invalid_assessment(state):
    h = state.create_hypothesis("q1", "Test")
    t = state.create_task(h.id, "Check something")
    state.claim_task("worker-1", task_type="general")

    with pytest.raises(ValueError, match="Invalid assessment"):
        state.complete_task(t.id, found=True, summary="x",
                            evidence=[], assessment="maybe")


def test_complete_task_already_done(state):
    h = state.create_hypothesis("q1", "Test")
    t = state.create_task(h.id, "Check something")
    state.claim_task("worker-1", task_type="general")
    state.complete_task(t.id, found=True, summary="x",
                        evidence=[], assessment="neutral")

    with pytest.raises(ValueError, match="already complete"):
        state.complete_task(t.id, found=True, summary="y",
                            evidence=[], assessment="neutral")


def test_complete_nonexistent_task(state):
    with pytest.raises(ValueError, match="not found"):
        state.complete_task("bad-id", found=True, summary="x",
                            evidence=[], assessment="neutral")


# ───────────────────────────────────────────────────────────────────
# Task timeout / reaping
# ───────────────────────────────────────────────────────────────────


def test_timed_out_task_is_reaped(state, monkeypatch):
    import mcp_tools._state as mod
    monkeypatch.setattr(mod, "TASK_TIMEOUT_SECONDS", 0)

    h = state.create_hypothesis("q1", "Test")
    t = state.create_task(h.id, "Slow task", task_type="general")

    # First worker claims it
    state.claim_task("worker-1", task_type="general")

    # Simulate timeout by claiming again (timeout=0 means immediately expired)
    reclaimed, _ = state.claim_task("worker-2", task_type="general")
    assert reclaimed is not None
    assert reclaimed.id == t.id
    assert reclaimed.claimed_by == "worker-2"


# ───────────────────────────────────────────────────────────────────
# Investigation-level reads
# ───────────────────────────────────────────────────────────────────


def test_get_summary(state):
    h = state.create_hypothesis("q1", "Test")
    state.create_task(h.id, "Task A")
    state.create_task(h.id, "Task B")
    state.set_queue_open(True)

    summary = state.get_summary()
    assert summary["queue_open"] is True
    assert summary["task_counts"]["pending"] == 2
    assert summary["total_hypotheses"] == 1
    assert len(summary["open_hypotheses"]) == 1


def test_get_pending_review_empty(state):
    result = state.get_pending_review()
    assert result["new_completed_tasks"] == 0
    assert result["by_hypothesis"] == {}


def test_get_pending_review_returns_new_completions(state):
    h = state.create_hypothesis("q1", "Test")
    t = state.create_task(h.id, "Task A")
    state.claim_task("w1", task_type="general")
    state.complete_task(t.id, found=True, summary="Done",
                        evidence=["x"], assessment="supports")

    result = state.get_pending_review()
    assert result["new_completed_tasks"] == 1
    assert h.id in result["by_hypothesis"]

    # Second call should return nothing new
    result2 = state.get_pending_review()
    assert result2["new_completed_tasks"] == 0


def test_get_full_state(state):
    h = state.create_hypothesis("q1", "Test")
    state.create_task(h.id, "Task A")

    full = state.get_full_state()
    assert "hypotheses" in full
    assert "tasks" in full
    assert "queue_open" in full
    assert len(full["hypotheses"]) == 1
    assert len(full["tasks"]) == 1


# ───────────────────────────────────────────────────────────────────
# Reset
# ───────────────────────────────────────────────────────────────────


def test_reset_clears_everything(state):
    h = state.create_hypothesis("q1", "Test")
    state.create_task(h.id, "Task A")
    state.set_queue_open(True)

    state.reset()
    assert state.hypotheses == {}
    assert state.tasks == {}
    assert state.queue_open is False


# ───────────────────────────────────────────────────────────────────
# Persistence
# ───────────────────────────────────────────────────────────────────


def test_state_persists_to_disk(state, tmp_path):
    import mcp_tools._state as mod
    state_file = mod.STATE_FILE

    h = state.create_hypothesis("q1", "Persisted hypothesis")
    state.create_task(h.id, "Persisted task")

    assert os.path.exists(state_file)
    with open(state_file) as f:
        data = json.load(f)
    assert len(data["hypotheses"]) == 1
    assert len(data["tasks"]) == 1


def test_state_reloads_from_disk(state, tmp_path):
    import mcp_tools._state as mod

    h = state.create_hypothesis("q1", "Will reload")
    state.create_task(h.id, "Task to reload")

    # Create a new instance pointing at the same file
    s2 = InvestigationState()
    summary = s2.get_summary()
    assert summary["total_hypotheses"] == 1
    assert summary["task_counts"]["pending"] == 1
