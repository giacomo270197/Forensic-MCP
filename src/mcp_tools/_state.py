import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "investigation_state.json")

_lock = threading.Lock()

# Fix 3: tasks claimed longer than this are considered abandoned and reset.
TASK_TIMEOUT_SECONDS = int(os.environ.get("TASK_TIMEOUT_SECONDS", "300"))


class HypothesisStatus(str, Enum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"


class TaskStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    DONE = "done"


# Fix 2: explicit assessment values that complete_task accepts
class TaskAssessment(str, Enum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    NEUTRAL = "neutral"


@dataclass
class Hypothesis:
    id: str
    question_id: str
    statement: str
    status: str = HypothesisStatus.OPEN
    supporting_task_ids: list = field(default_factory=list)
    refuting_task_ids: list = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)  # Fix 4


@dataclass
class Task:
    id: str
    hypothesis_id: str
    description: str
    task_type: str = "general"           # Worker filter tag set by Investigator
    status: str = TaskStatus.PENDING
    # Fix 5: structured result instead of free string
    result: Optional[dict] = None
    claimed_by: Optional[str] = None
    claimed_at: Optional[float] = None   # Fix 3
    completed_at: Optional[float] = None  # Fix 4


class InvestigationState:
    def __init__(self):
        self.hypotheses: dict[str, Hypothesis] = {}
        self.tasks: dict[str, Task] = {}
        self.queue_open: bool = False        # Fix 1
        self.last_review_ts: float = 0.0    # Fix 4

    def _load(self):
        path = os.path.abspath(STATE_FILE)
        if not os.path.exists(path):
            return
        with open(path, "r") as f:
            raw = json.load(f)
        self.hypotheses = {
            hid: Hypothesis(**h) for hid, h in raw.get("hypotheses", {}).items()
        }
        self.tasks = {
            tid: Task(**t) for tid, t in raw.get("tasks", {}).items()
        }
        self.queue_open = raw.get("queue_open", False)
        self.last_review_ts = raw.get("last_review_ts", 0.0)

    def _save(self):
        path = os.path.abspath(STATE_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(
                {
                    "hypotheses": {hid: asdict(h) for hid, h in self.hypotheses.items()},
                    "tasks": {tid: asdict(t) for tid, t in self.tasks.items()},
                    "queue_open": self.queue_open,
                    "last_review_ts": self.last_review_ts,
                },
                f,
                indent=2,
            )

    # ── Queue control (Fix 1) ──────────────────────────────────────────────

    def set_queue_open(self, open: bool) -> None:
        with _lock:
            self._load()
            self.queue_open = open
            self._save()

    # ── Hypothesis operations ──────────────────────────────────────────────

    def create_hypothesis(self, question_id: str, statement: str) -> Hypothesis:
        with _lock:
            self._load()
            h = Hypothesis(
                id=str(uuid.uuid4()),
                question_id=question_id,
                statement=statement,
            )
            self.hypotheses[h.id] = h
            self._save()
            return h

    def update_hypothesis(
        self,
        hypothesis_id: str,
        new_statement: Optional[str] = None,
        new_status: Optional[str] = None,
    ) -> Hypothesis:
        with _lock:
            self._load()
            h = self.hypotheses.get(hypothesis_id)
            if h is None:
                raise ValueError(f"Hypothesis {hypothesis_id} not found")
            if new_statement is not None:
                h.statement = new_statement
            if new_status is not None:
                if new_status not in HypothesisStatus.__members__.values():
                    raise ValueError(
                        f"Invalid status '{new_status}'. Must be one of: "
                        + ", ".join(s.value for s in HypothesisStatus)
                    )
                h.status = new_status
            h.updated_at = time.time()  # Fix 4
            self._save()
            return h

    def list_hypotheses(self, question_id: Optional[str] = None) -> list[Hypothesis]:
        with _lock:
            self._load()
            hs = list(self.hypotheses.values())
            if question_id is not None:
                hs = [h for h in hs if h.question_id == question_id]
            return hs

    # ── Task operations ────────────────────────────────────────────────────

    def create_task(self, hypothesis_id: str, description: str, task_type: str = "general") -> Task:
        with _lock:
            self._load()
            if hypothesis_id not in self.hypotheses:
                raise ValueError(f"Hypothesis {hypothesis_id} not found")
            t = Task(
                id=str(uuid.uuid4()),
                hypothesis_id=hypothesis_id,
                description=description,
                task_type=task_type,
            )
            self.tasks[t.id] = t
            self._save()
            return t

    def claim_task(self, worker_id: str, task_type: Optional[str] = None) -> tuple[Optional[Task], bool]:
        """
        Atomically claim the oldest pending task matching task_type.

        Fix 1: returns (task, queue_open) so callers can distinguish
               "nothing now but more coming" from "queue is closed, stop".
        Fix 3: reaps timed-out claimed tasks back to pending before
               returning the next one.
        task_type: if provided, only tasks with a matching task_type are
                   eligible. If None, claims the next pending task of any type.
        """
        with _lock:
            self._load()
            now = time.time()

            # Fix 3: reap abandoned claimed tasks (all types)
            for t in self.tasks.values():
                if (
                    t.status == TaskStatus.CLAIMED
                    and t.claimed_at is not None
                    and now - t.claimed_at > TASK_TIMEOUT_SECONDS
                ):
                    t.status = TaskStatus.PENDING
                    t.claimed_by = None
                    t.claimed_at = None

            # Claim the first pending task matching the requested type
            task = next(
                (
                    t for t in self.tasks.values()
                    if t.status == TaskStatus.PENDING
                    and (task_type is None or t.task_type == task_type)
                ),
                None,
            )
            if task is not None:
                task.status = TaskStatus.CLAIMED
                task.claimed_by = worker_id
                task.claimed_at = now
            self._save()
            return task, self.queue_open

    def complete_task(
        self,
        task_id: str,
        found: bool,
        summary: str,
        evidence: list[str],
        assessment: str,
    ) -> Task:
        """
        Fix 2: assessment param drives hypothesis supporting/refuting lists.
        Fix 5: result stored as structured dict.
        """
        with _lock:
            self._load()
            t = self.tasks.get(task_id)
            if t is None:
                raise ValueError(f"Task {task_id} not found")
            if t.status == TaskStatus.DONE:
                raise ValueError(f"Task {task_id} is already complete")

            if assessment not in TaskAssessment.__members__.values():
                raise ValueError(
                    f"Invalid assessment '{assessment}'. Must be one of: "
                    + ", ".join(a.value for a in TaskAssessment)
                )

            # Fix 5: structured result
            t.result = {"found": found, "summary": summary, "evidence": evidence}
            t.status = TaskStatus.DONE
            t.completed_at = time.time()  # Fix 4

            # Fix 2: update parent hypothesis evidence lists
            h = self.hypotheses.get(t.hypothesis_id)
            if h is not None:
                if assessment == TaskAssessment.SUPPORTS:
                    if task_id not in h.supporting_task_ids:
                        h.supporting_task_ids.append(task_id)
                elif assessment == TaskAssessment.REFUTES:
                    if task_id not in h.refuting_task_ids:
                        h.refuting_task_ids.append(task_id)
                h.updated_at = time.time()  # Fix 4

            self._save()
            return t

    # ── Investigation-level reads (Fix 4) ─────────────────────────────────

    def get_summary(self) -> dict:
        """
        Cheap summary for the Investigator to orient itself without reading
        all task results. Returns counts and open hypotheses only.
        """
        with _lock:
            self._load()
            task_counts: dict[str, int] = {"pending": 0, "claimed": 0, "done": 0}
            for t in self.tasks.values():
                task_counts[t.status] = task_counts.get(t.status, 0) + 1

            open_hypotheses = [
                {
                    "id": h.id,
                    "question_id": h.question_id,
                    "statement": h.statement,
                    "status": h.status,
                    "supporting_count": len(h.supporting_task_ids),
                    "refuting_count": len(h.refuting_task_ids),
                }
                for h in self.hypotheses.values()
                if h.status == HypothesisStatus.OPEN
            ]
            return {
                "queue_open": self.queue_open,
                "task_counts": task_counts,
                "open_hypotheses": open_hypotheses,
                "total_hypotheses": len(self.hypotheses),
            }

    def get_pending_review(self) -> dict:
        """
        Return only tasks completed since the last call to this method,
        grouped by hypothesis. Advances the internal review cursor.
        """
        with _lock:
            self._load()
            since = self.last_review_ts
            new_tasks = [
                t for t in self.tasks.values()
                if t.status == TaskStatus.DONE
                and t.completed_at is not None
                and t.completed_at > since
            ]

            # Group by hypothesis
            by_hypothesis: dict[str, dict] = {}
            for t in new_tasks:
                hid = t.hypothesis_id
                if hid not in by_hypothesis:
                    h = self.hypotheses.get(hid)
                    by_hypothesis[hid] = {
                        "hypothesis": asdict(h) if h else None,
                        "completed_tasks": [],
                    }
                by_hypothesis[hid]["completed_tasks"].append(asdict(t))

            self.last_review_ts = time.time()
            self._save()
            return {
                "since": since,
                "reviewed_at": self.last_review_ts,
                "new_completed_tasks": len(new_tasks),
                "by_hypothesis": by_hypothesis,
            }

    def get_full_state(self) -> dict:
        """Full dump for debugging or final reporting. Avoid in tight loops."""
        with _lock:
            self._load()
            return {
                "queue_open": self.queue_open,
                "hypotheses": {hid: asdict(h) for hid, h in self.hypotheses.items()},
                "tasks": {tid: asdict(t) for tid, t in self.tasks.items()},
            }

    def reset(self):
        """Wipe all state. Closes the queue. Use at the start of a new case."""
        with _lock:
            self.hypotheses = {}
            self.tasks = {}
            self.queue_open = False
            self.last_review_ts = 0.0
            self._save()


# Module-level singleton
_state = InvestigationState()


def get_state() -> InvestigationState:
    return _state
