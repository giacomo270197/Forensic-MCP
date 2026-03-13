"""
MCP tools — investigation planning.

Exposed tools
─────────────
  initialize_plan     Start a new investigation plan (default or custom phases).
  get_plan_summary    High-level status: current phase, goal counts, phase breakdown.
  get_current_phase   Full detail on the active phase including all goals.
  add_goal            Add a goal to any non-complete phase.
  complete_goal       Mark a goal done; auto-advances phase when all goals finish.
  add_phase           Insert a custom phase anywhere in the plan.
  skip_phase          Skip a pending or active phase with a recorded reason.
  list_phases         Ordered list of all phases and their statuses.
"""

from __future__ import annotations

import os
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp_tools._investigation import InvestigationPlan

# ---------------------------------------------------------------------------
# Singleton — path configurable via env var
# ---------------------------------------------------------------------------

_PLAN_PATH = os.environ.get("INVESTIGATION_PLAN_PATH", "investigation_plan.json")
_plan = InvestigationPlan(path=_PLAN_PATH)


def register_tools(mcp: FastMCP) -> None:
    """Call once from forensics_mcp.py to register all planning tools."""

    # ------------------------------------------------------------------
    @mcp.tool()
    def initialize_plan(
        case_name: str,
        custom_phases: Optional[list[dict]] = None,
    ) -> dict:
        """
        Start a new investigation plan.

        Parameters
        ----------
        case_name : str
            Human-readable case identifier, e.g. "ACME-IR-2024-001".
        custom_phases : list[dict], optional
            Override the default phase list.  Each entry must have
            "name" (str) and "description" (str).  If omitted, the
            standard 8-phase forensics workflow is used:
              initial_triage → initial_compromise → execution →
              persistence → lateral_movement → collection →
              exfiltration → impact

        Returns the full plan dict with the first phase already active.
        """
        return _plan.initialize(case_name, custom_phases)

    # ------------------------------------------------------------------
    @mcp.tool()
    def get_plan_summary() -> dict:
        """
        Return a high-level summary of the current investigation plan.

        Includes: case name, plan ID, current active phase, open/closed
        goal counts for the active phase, and a breakdown of phase statuses.

        Use this at the start of each Interviewer turn to orient yourself.
        """
        return _plan.summary()

    # ------------------------------------------------------------------
    @mcp.tool()
    def get_current_phase() -> dict:
        """
        Return full details of the currently active phase, including all
        its goals and their statuses.

        Returns {"status": "complete", ...} when all phases are resolved.
        """
        return _plan.get_current_phase()

    # ------------------------------------------------------------------
    @mcp.tool()
    def list_phases() -> list[dict]:
        """
        Return all phases in order with id, name, status, and goal counts.
        Goals themselves are not included — use get_current_phase() for that.
        """
        plan = _plan.get_plan()
        result = []
        for ph in plan["phases"]:
            result.append({
                "id":          ph["id"],
                "name":        ph["name"],
                "description": ph["description"],
                "status":      ph["status"],
                "goal_count":  len(ph["goals"]),
                "open_goals":  sum(1 for g in ph["goals"] if g["status"] == "open"),
            })
        return result

    # ------------------------------------------------------------------
    @mcp.tool()
    def add_goal(phase_id: str, description: str) -> dict:
        """
        Add a new open goal to a phase.

        Parameters
        ----------
        phase_id : str
            ID of the target phase (get IDs from list_phases).
        description : str
            What needs to be answered or confirmed, e.g.
            "Confirm whether lsass.exe was dumped using Task Manager."

        Cannot add goals to completed or skipped phases.
        Returns the new goal dict including its assigned ID.
        """
        return _plan.add_goal(phase_id, description)

    # ------------------------------------------------------------------
    @mcp.tool()
    def complete_goal(goal_id: str, notes: Optional[str] = None) -> dict:
        """
        Mark a goal as complete.

        When ALL goals in the current phase are complete, the phase is
        automatically marked complete and the next pending phase is
        activated.

        Parameters
        ----------
        goal_id : str
            ID of the goal to complete (visible in get_current_phase output).
        notes : str, optional
            Brief summary of the finding that satisfies this goal.
            Good notes become part of the investigation audit trail.

        Returns
        -------
        {
          "goal":           <goal dict>,
          "phase_advanced": true | false,
          "new_phase":      "<phase name>" | null
        }
        """
        return _plan.complete_goal(goal_id, notes)

    # ------------------------------------------------------------------
    @mcp.tool()
    def add_phase(
        name: str,
        description: str,
        after_phase_id: Optional[str] = None,
    ) -> dict:
        """
        Insert a custom phase into the plan.

        Use this when findings reveal an investigative branch not covered
        by the default phases, e.g. "cloud_persistence" or "supply_chain".

        Parameters
        ----------
        name : str
            Short identifier, snake_case preferred.
        description : str
            What this phase is trying to establish.
        after_phase_id : str, optional
            Insert immediately after this phase.  If omitted, appends
            at the end of the plan.

        The new phase starts as "pending" and will become active in turn.
        Returns the new phase dict including its assigned ID.
        """
        return _plan.add_phase(name, description, after_phase_id)

    # ------------------------------------------------------------------
    @mcp.tool()
    def skip_phase(phase_id: str, reason: str) -> dict:
        """
        Skip a phase that is not relevant to this investigation.

        Example: skip "exfiltration" for a ransomware-only case where
        no data theft is suspected.

        Parameters
        ----------
        phase_id : str
            ID of the phase to skip.
        reason : str
            Justification recorded in the audit trail, e.g.
            "No network egress artefacts found; ransomware-only IOCs."

        If the skipped phase was active, the next pending phase is
        immediately activated.
        Returns the updated phase dict.
        """
        return _plan.skip_phase(phase_id, reason)
