"""
mcp_tools._questions
====================
Persistent question/answer queue — shared blackboard across three agent tiers.

Each question is stored as a JSON file on disk under:
    <output_dir>/questions/<question_id>.json

Question lifecycle
------------------
  pending  →  in_progress  →  answered
                            →  failed

Agent routing
-------------
Each question carries an `assigned_role` field that controls which agent
type may claim it via get_next_question(agent_role=...).

  depth=0, assigned_role="investigator"
      Submitted by the Interviewer. Claimed by the Investigator.
      The Investigator decomposes it into depth=1 sub-questions.

  depth=1, assigned_role="parser:<Artefact>"
      Submitted by the Investigator. Claimed only by the Parser agent
      whose role matches exactly, e.g. "parser:Prefetch".
      evidence_hints[0] determines which parser the sub-question targets.

The Investigator polls list_questions(parent_id=<id>) to check whether
all its sub-questions are answered, then coalesces and answers the parent.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class Question:
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    ANSWERED    = "answered"
    FAILED      = "failed"

    def __init__(
        self,
        question_id:    str,
        text:           str,
        hypothesis:     str,
        evidence_hints: list[str],
        priority:       int,
        depth:          int,
        assigned_role:  str,
        base_dir:       Path,
        parent_id:      str | None = None,
    ) -> None:
        self.question_id    = question_id
        self.text           = text
        self.hypothesis     = hypothesis
        self.evidence_hints = evidence_hints
        self.priority       = priority
        self.depth          = depth           # 0 = Interviewer→Investigator
                                              # 1 = Investigator→Parser
        self.assigned_role  = assigned_role   # "investigator" | "parser:<Artefact>"
        self.parent_id      = parent_id
        self.status         = self.PENDING
        self.answer:        str  = ""
        self.answer_detail: dict = {}
        self.created_at     = _now()
        self.updated_at     = _now()
        self._path          = base_dir / f"{question_id}.json"

    def _save(self) -> None:
        self.updated_at = _now()
        self._path.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )

    @classmethod
    def _from_dict(cls, data: dict, base_dir: Path) -> "Question":
        q               = cls.__new__(cls)
        q.question_id   = data["question_id"]
        q.text          = data["text"]
        q.hypothesis    = data["hypothesis"]
        q.evidence_hints = data.get("evidence_hints", [])
        q.priority      = data.get("priority", 3)
        q.depth         = data.get("depth", 0)
        q.assigned_role = data.get("assigned_role", "investigator")
        q.parent_id     = data.get("parent_id")
        q.status        = data["status"]
        q.answer        = data.get("answer", "")
        q.answer_detail = data.get("answer_detail", {})
        q.created_at    = data["created_at"]
        q.updated_at    = data["updated_at"]
        q._path         = base_dir / f"{q.question_id}.json"
        return q

    def claim(self) -> None:
        self.status = self.IN_PROGRESS
        self._save()

    def answer_question(self, answer: str, detail: dict | None = None) -> None:
        self.status        = self.ANSWERED
        self.answer        = answer
        self.answer_detail = detail or {}
        self._save()

    def fail(self, reason: str) -> None:
        self.status = self.FAILED
        self.answer = reason
        self._save()

    def to_dict(self) -> dict:
        return {
            "question_id":    self.question_id,
            "text":           self.text,
            "hypothesis":     self.hypothesis,
            "evidence_hints": self.evidence_hints,
            "priority":       self.priority,
            "depth":          self.depth,
            "assigned_role":  self.assigned_role,
            "parent_id":      self.parent_id,
            "status":         self.status,
            "answer":         self.answer,
            "answer_detail":  self.answer_detail,
            "created_at":     self.created_at,
            "updated_at":     self.updated_at,
        }

    def to_summary(self) -> dict:
        """Compact view — omits answer_detail to keep context small."""
        return {
            "question_id":   self.question_id,
            "text":          self.text,
            "hypothesis":    self.hypothesis,
            "priority":      self.priority,
            "depth":         self.depth,
            "assigned_role": self.assigned_role,
            "status":        self.status,
            "answer":        self.answer,
            "parent_id":     self.parent_id,
            "created_at":    self.created_at,
        }


class QuestionQueue:
    def __init__(self) -> None:
        self._questions: dict[str, Question] = {}
        self._base_dir:  Path | None         = None

    def _init_dir(self, output_dir: Path) -> Path:
        base = output_dir / "questions"
        base.mkdir(parents=True, exist_ok=True)
        self._base_dir = base
        return base

    def _load_from_disk(self, output_dir: Path) -> None:
        base = self._init_dir(output_dir)
        for path in base.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                q    = Question._from_dict(data, base)
                self._questions[q.question_id] = q
            except Exception:  # noqa: BLE001
                pass

    def _ensure_loaded(self, output_dir: Path) -> None:
        if self._base_dir is None:
            self._load_from_disk(output_dir)

    def submit(
        self,
        text:           str,
        hypothesis:     str,
        evidence_hints: list[str],
        priority:       int,
        depth:          int,
        assigned_role:  str,
        output_dir:     Path,
        parent_id:      str | None = None,
    ) -> Question:
        self._ensure_loaded(output_dir)
        base        = self._init_dir(output_dir)
        question_id = str(uuid.uuid4())[:8]
        q = Question(
            question_id    = question_id,
            text           = text,
            hypothesis     = hypothesis,
            evidence_hints = evidence_hints,
            priority       = priority,
            depth          = depth,
            assigned_role  = assigned_role,
            base_dir       = base,
            parent_id      = parent_id,
        )
        q._save()
        self._questions[question_id] = q
        return q

    def get_next_pending(self, agent_role: str, output_dir: Path) -> Question | None:
        """
        Return the highest-priority pending question assigned to `agent_role`
        and mark it in_progress atomically.
        Always re-reads from disk so questions from other agents are visible.
        """
        self._load_from_disk(output_dir)
        pending = [
            q for q in self._questions.values()
            if q.status         == Question.PENDING
            and q.assigned_role == agent_role
        ]
        if not pending:
            return None
        pending.sort(key=lambda q: (q.priority, q.created_at))
        q = pending[0]
        q.claim()
        return q

    def get(self, question_id: str, output_dir: Path) -> Question | None:
        self._load_from_disk(output_dir)
        return self._questions.get(question_id)

    def list_all(
        self,
        output_dir:  Path,
        status:      str | None = None,
        parent_id:   str | None = None,
        agent_role:  str | None = None,
    ) -> list[dict]:
        """Return question summaries with optional filters. Always re-reads from disk."""
        self._load_from_disk(output_dir)
        questions = list(self._questions.values())
        if status:
            questions = [q for q in questions if q.status == status]
        if parent_id:
            questions = [q for q in questions if q.parent_id == parent_id]
        if agent_role:
            questions = [q for q in questions if q.assigned_role == agent_role]
        questions.sort(key=lambda q: (q.depth, q.priority, q.created_at))
        return [q.to_summary() for q in questions]

    def all_children_answered(self, parent_id: str, output_dir: Path) -> bool:
        """
        True if every sub-question with this parent_id is answered or failed.
        Used by the Investigator to know when it can coalesce and answer the parent.
        """
        self._load_from_disk(output_dir)
        children = [q for q in self._questions.values() if q.parent_id == parent_id]
        if not children:
            return False
        return all(q.status in (Question.ANSWERED, Question.FAILED) for q in children)

    def pending_count(self, output_dir: Path, agent_role: str | None = None) -> int:
        self._load_from_disk(output_dir)
        return sum(
            1 for q in self._questions.values()
            if q.status == Question.PENDING
            and (agent_role is None or q.assigned_role == agent_role)
        )

    def answered_count(self, output_dir: Path) -> int:
        self._load_from_disk(output_dir)
        return sum(1 for q in self._questions.values() if q.status == Question.ANSWERED)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


question_queue = QuestionQueue()