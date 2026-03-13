"""
Disk-backed InvestigationPlan — manages phases, goals, and auto-advance logic.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PHASES = [
    ("initial_triage",    "Establish scope: victim machines, timeframe, artefact inventory."),
    ("initial_compromise","Identify the entry point: phishing, exploit, stolen creds, etc."),
    ("execution",         "Determine what ran: processes, scripts, LOLBins, malware drops."),
    ("persistence",       "Find persistence mechanisms: scheduled tasks, registry run keys, services."),
    ("lateral_movement",  "Trace movement across hosts: pass-the-hash, RDP, SMB, WMI."),
    ("collection",        "Identify data staged for exfiltration: archives, shadow copies, clipboard."),
    ("exfiltration",      "Confirm data left the network: DNS, HTTPS, cloud uploads."),
    ("impact",            "Assess damage: ransomware, wiped logs, destroyed backups."),
]

PhaseStatus = Literal["pending", "active", "complete", "skipped"]
GoalStatus  = Literal["open", "complete"]


# ---------------------------------------------------------------------------
# Data classes (plain dicts serialised to JSON — no dataclass dependency)
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_goal(description: str) -> dict:
    return {
        "id":           str(uuid.uuid4())[:8],
        "description":  description,
        "status":       "open",
        "completed_at": None,
        "notes":        None,
    }


def _new_phase(name: str, description: str) -> dict:
    return {
        "id":          str(uuid.uuid4())[:8],
        "name":        name,
        "description": description,
        "status":      "pending",
        "goals":       [],
        "started_at":  None,
        "completed_at": None,
    }


# ---------------------------------------------------------------------------
# InvestigationPlan
# ---------------------------------------------------------------------------

class InvestigationPlan:
    """
    Persists the full investigation plan as a single JSON file.

    Thread-safety: load-modify-save on every mutation (good enough for
    single-process MCP server; add a filelock if you need concurrency).
    """

    def __init__(self, path: str | Path = "investigation_plan.json"):
        self._path = Path(path)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if self._path.exists():
            return json.loads(self._path.read_text())
        return {}

    def _save(self, plan: dict) -> None:
        self._path.write_text(json.dumps(plan, indent=2))

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialize(
        self,
        case_name: str,
        custom_phases: Optional[list[dict]] = None,
    ) -> dict:
        """
        Create a fresh plan.  Pass custom_phases=[{"name":..,"description":..}]
        to override defaults entirely, or leave None to use the default set.
        """
        phase_specs = custom_phases or [
            {"name": n, "description": d} for n, d in DEFAULT_PHASES
        ]
        phases = [_new_phase(p["name"], p["description"]) for p in phase_specs]

        # Activate the first phase immediately
        if phases:
            phases[0]["status"] = "active"
            phases[0]["started_at"] = _now()

        plan = {
            "plan_id":    str(uuid.uuid4())[:8],
            "case_name":  case_name,
            "created_at": _now(),
            "updated_at": _now(),
            "phases":     phases,
        }
        self._save(plan)
        return plan

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_plan(self) -> dict:
        plan = self._load()
        if not plan:
            raise ValueError("No investigation plan exists. Call initialize_plan first.")
        return plan

    def get_current_phase(self) -> dict:
        plan = self.get_plan()
        for phase in plan["phases"]:
            if phase["status"] == "active":
                return phase
        # All phases complete or skipped
        return {"status": "complete", "message": "All phases resolved."}

    def _find_phase(self, plan: dict, phase_id: str) -> tuple[int, dict]:
        for i, ph in enumerate(plan["phases"]):
            if ph["id"] == phase_id:
                return i, ph
        raise ValueError(f"Phase '{phase_id}' not found.")

    def _find_goal(self, plan: dict, goal_id: str) -> tuple[dict, dict]:
        """Returns (phase, goal)."""
        for phase in plan["phases"]:
            for goal in phase["goals"]:
                if goal["id"] == goal_id:
                    return phase, goal
        raise ValueError(f"Goal '{goal_id}' not found.")

    # ------------------------------------------------------------------
    # Goal operations
    # ------------------------------------------------------------------

    def add_goal(self, phase_id: str, description: str) -> dict:
        plan = self._load()
        _, phase = self._find_phase(plan, phase_id)
        if phase["status"] in ("complete", "skipped"):
            raise ValueError(f"Cannot add goal to a {phase['status']} phase.")
        goal = _new_goal(description)
        phase["goals"].append(goal)
        plan["updated_at"] = _now()
        self._save(plan)
        return goal

    def complete_goal(self, goal_id: str, notes: Optional[str] = None) -> dict:
        """
        Mark a goal complete.  If all goals in the phase are now complete,
        auto-advance to the next pending phase.
        """
        plan = self._load()
        phase, goal = self._find_goal(plan, goal_id)

        if goal["status"] == "complete":
            return {"goal": goal, "phase_advanced": False, "message": "Goal already complete."}

        goal["status"]       = "complete"
        goal["completed_at"] = _now()
        goal["notes"]        = notes
        plan["updated_at"]   = _now()

        # Auto-advance check
        phase_advanced = False
        new_phase_name = None
        all_done = all(g["status"] == "complete" for g in phase["goals"])

        if all_done and phase["goals"]:  # don't auto-advance empty phases
            phase["status"]       = "complete"
            phase["completed_at"] = _now()
            phase_advanced        = True

            # Activate next pending phase
            for ph in plan["phases"]:
                if ph["status"] == "pending":
                    ph["status"]     = "active"
                    ph["started_at"] = _now()
                    new_phase_name   = ph["name"]
                    break

        self._save(plan)
        return {
            "goal":           goal,
            "phase_advanced": phase_advanced,
            "new_phase":      new_phase_name,
        }

    # ------------------------------------------------------------------
    # Phase operations
    # ------------------------------------------------------------------

    def add_phase(
        self,
        name: str,
        description: str,
        after_phase_id: Optional[str] = None,
    ) -> dict:
        """
        Insert a new phase.  If after_phase_id is None, append at end.
        The new phase starts as 'pending' regardless of position.
        """
        plan = self._load()
        new_ph = _new_phase(name, description)

        if after_phase_id is None:
            plan["phases"].append(new_ph)
        else:
            idx, _ = self._find_phase(plan, after_phase_id)
            plan["phases"].insert(idx + 1, new_ph)

        plan["updated_at"] = _now()
        self._save(plan)
        return new_ph

    def skip_phase(self, phase_id: str, reason: str) -> dict:
        """
        Skip a pending or active phase.  If active, activate the next pending one.
        """
        plan  = self._load()
        _, ph = self._find_phase(plan, phase_id)

        if ph["status"] == "complete":
            raise ValueError("Cannot skip a completed phase.")

        was_active = ph["status"] == "active"
        ph["status"]       = "skipped"
        ph["completed_at"] = _now()
        ph["notes"]        = reason  # store skip reason here
        plan["updated_at"] = _now()

        if was_active:
            for p in plan["phases"]:
                if p["status"] == "pending":
                    p["status"]     = "active"
                    p["started_at"] = _now()
                    break

        self._save(plan)
        return ph

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        plan  = self.get_plan()
        total = len(plan["phases"])
        by_status: dict[str, int] = {}
        for ph in plan["phases"]:
            by_status[ph["status"]] = by_status.get(ph["status"], 0) + 1

        current = self.get_current_phase()
        open_goals   = sum(1 for g in current.get("goals", []) if g["status"] == "open")
        closed_goals = sum(1 for g in current.get("goals", []) if g["status"] == "complete")

        return {
            "case_name":         plan["case_name"],
            "plan_id":           plan["plan_id"],
            "total_phases":      total,
            "phase_counts":      by_status,
            "current_phase":     current.get("name", "—"),
            "current_phase_id":  current.get("id"),
            "open_goals":        open_goals,
            "closed_goals":      closed_goals,
        }
