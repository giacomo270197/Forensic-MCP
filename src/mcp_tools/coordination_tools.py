from fastmcp import FastMCP
from mcp_tools._state import get_state, HypothesisStatus, TaskAssessment


def register_tools(mcp: FastMCP):

    # ── Investigator tools ─────────────────────────────────────────────────

    @mcp.tool()
    def open_task_queue() -> dict:
        """
        Open the task queue so Workers can start claiming tasks.

        Call this once you have created an initial batch of tasks and are
        ready for Workers to begin. You can continue adding tasks while the
        queue is open — Workers will pick them up automatically.

        Do not open the queue before creating at least one task, or Workers
        will see an empty open queue and wait indefinitely.

        Returns the current queue status.
        """
        get_state().set_queue_open(True)
        return {"queue_open": True}

    @mcp.tool()
    def close_task_queue() -> dict:
        """
        Close the task queue to signal Workers that no more tasks are coming.

        Call this when the investigation is complete and you will not be
        creating any more tasks. Workers that finish their current task and
        find the queue empty and closed will terminate.

        Returns the current queue status.
        """
        get_state().set_queue_open(False)
        return {"queue_open": False}

    @mcp.tool()
    def create_hypothesis(question_id: str, statement: str) -> dict:
        """
        Create a new hypothesis that attempts to answer one of the investigation
        questions defined in the prompt.

        Args:
            question_id: Identifier for the question this hypothesis addresses
                         (e.g. "initial_access", "data_exfiltration"). Must
                         match a question defined in the investigation prompt.
            statement:   A specific, falsifiable claim about what happened
                         (e.g. "Initial access was achieved via brute-force RDP").

        Returns the created hypothesis including its assigned id.
        """
        h = get_state().create_hypothesis(question_id=question_id, statement=statement)
        return {
            "id": h.id,
            "question_id": h.question_id,
            "statement": h.statement,
            "status": h.status,
            "supporting_task_ids": h.supporting_task_ids,
            "refuting_task_ids": h.refuting_task_ids,
        }

    @mcp.tool()
    def update_hypothesis(
        hypothesis_id: str,
        new_statement: str | None = None,
        new_status: str | None = None,
    ) -> dict:
        """
        Revise or close a hypothesis as evidence accumulates.

        Use get_pending_review() to retrieve completed task results, then
        call this to record your assessment of what they mean.

        Args:
            hypothesis_id: ID of the hypothesis to update.
            new_statement: Revised claim text, if partial evidence points to
                           a more specific version of the hypothesis.
            new_status:    One of "open", "confirmed", or "refuted".
                           "confirmed": multiple supporting tasks provide
                             consistent, unambiguous evidence.
                           "refuted": tasks have conclusively ruled it out.
                           Do not confirm on the basis of a single task result
                           unless the evidence is unambiguous.

        Returns the updated hypothesis.
        """
        h = get_state().update_hypothesis(
            hypothesis_id=hypothesis_id,
            new_statement=new_statement,
            new_status=new_status,
        )
        return {
            "id": h.id,
            "question_id": h.question_id,
            "statement": h.statement,
            "status": h.status,
            "supporting_task_ids": h.supporting_task_ids,
            "refuting_task_ids": h.refuting_task_ids,
            "updated_at": h.updated_at,
        }

    @mcp.tool()
    def list_hypotheses(question_id: str | None = None) -> list[dict]:
        """
        List all hypotheses, optionally filtered to a single question.

        Args:
            question_id: If provided, only return hypotheses for this question.
                         Omit to return all hypotheses across all questions.
        """
        hs = get_state().list_hypotheses(question_id=question_id)
        return [
            {
                "id": h.id,
                "question_id": h.question_id,
                "statement": h.statement,
                "status": h.status,
                "supporting_task_ids": h.supporting_task_ids,
                "refuting_task_ids": h.refuting_task_ids,
                "updated_at": h.updated_at,
            }
            for h in hs
        ]

    @mcp.tool()
    def create_task(hypothesis_id: str, description: str, task_type: str = "general") -> dict:
        """
        Create a concrete investigative task that would help validate or
        refute a hypothesis.

        Tasks are placed in a shared queue. Workers filter the queue by
        task_type, so only Workers of the matching type will be presented
        with this task.

        Args:
            hypothesis_id: The hypothesis this task relates to.
            description:   Actionable description of what to check and why.
                           Must be self-contained: include the evidence source,
                           specific indicators, time window, and what to report.
            task_type:     Tag that determines which Worker type will handle
                           this task (e.g. "evtx", "filesystem", "registry").
                           Must match the task_type a Worker passes to
                           claim_task. Defaults to "general" (claimed by any
                           Worker that passes task_type="general" or no filter).

        Returns the created task including its assigned id.
        """
        t = get_state().create_task(
            hypothesis_id=hypothesis_id,
            description=description,
            task_type=task_type,
        )
        return {
            "id": t.id,
            "hypothesis_id": t.hypothesis_id,
            "description": t.description,
            "task_type": t.task_type,
            "status": t.status,
        }

    @mcp.tool()
    def get_investigation_state() -> dict:
        """
        Return a lightweight summary of the investigation's current state.

        Returns task counts by status, all open (unresolved) hypotheses with
        their supporting/refuting evidence counts, and whether the queue is open.

        Use this to orient yourself or check overall progress. To read the
        actual results of completed tasks, call get_pending_review() instead —
        it returns only what is new since your last review and is far cheaper
        on context.

        For a full raw dump of all state (debugging / final report), call
        get_full_investigation_state().
        """
        return get_state().get_summary()

    @mcp.tool()
    def get_pending_review() -> dict:
        """
        Return all tasks completed since the last time you called this tool,
        grouped by hypothesis.

        This is the primary tool for synthesising Worker results. Call it
        periodically to pick up new findings, then call update_hypothesis()
        for each affected hypothesis.

        The cursor advances on every call — results are not repeated.

        Returns:
            new_completed_tasks: count of tasks in this batch
            by_hypothesis: dict mapping hypothesis_id to the hypothesis object
                           and a list of its newly completed tasks, each
                           containing the structured result (found, summary,
                           evidence) and the assessment the Worker assigned.
        """
        return get_state().get_pending_review()

    @mcp.tool()
    def get_full_investigation_state() -> dict:
        """
        Return the complete raw state: all hypotheses and all tasks.

        Use sparingly — this dumps everything and will be large in a
        non-trivial investigation. Prefer get_investigation_state() for
        progress checks and get_pending_review() for reading results.

        Useful for: producing a final report, debugging unexpected state,
        or resuming an investigation after a context reset.
        """
        return get_state().get_full_state()

    @mcp.tool()
    def reset_investigation() -> dict:
        """
        Wipe all hypotheses, tasks, and queue state and start fresh.

        Also closes the task queue. Use at the beginning of a new case.
        Does not affect the Questions defined in the prompt.
        """
        get_state().reset()
        return {"status": "ok", "message": "Investigation state cleared."}

    # ── Worker tools ───────────────────────────────────────────────────────

    @mcp.tool()
    def claim_task(worker_id: str, task_type: str = "general") -> dict:
        """
        Claim the next pending task from the queue matching this Worker's type.

        Only tasks tagged with a matching task_type by the Investigator will
        be returned. This ensures Workers only see work relevant to their
        evidence scope and keeps each Worker's context focused.

        Call this at startup and after completing each task. The response
        tells you both whether a task is available and whether the queue
        is still open.

        Termination logic:
        - task != null               → execute the task, then call claim_task again
        - task == null, queue_open   → no matching work right now but more may
                                       come; wait briefly and call claim_task again
        - task == null, !queue_open  → investigation is complete; terminate

        Note: tasks not completed within the server's timeout threshold
        (default 5 minutes, configurable via TASK_TIMEOUT_SECONDS env var)
        are automatically returned to the queue and may be reassigned.

        Args:
            worker_id:  Short identifier for this Worker instance.
            task_type:  The type of tasks this Worker handles. Only tasks
                        tagged with this type by the Investigator will be
                        returned. Must match the task_type used in create_task.
        """
        task, queue_open = get_state().claim_task(worker_id=worker_id, task_type=task_type)
        if task is None:
            return {"task": None, "queue_open": queue_open}
        return {
            "task": {
                "id": task.id,
                "hypothesis_id": task.hypothesis_id,
                "description": task.description,
                "task_type": task.task_type,
                "claimed_by": task.claimed_by,
            },
            "queue_open": queue_open,
        }

    @mcp.tool()
    def complete_task(
        task_id: str,
        found: bool,
        summary: str,
        evidence: list[str],
        assessment: str,
    ) -> dict:
        """
        Submit the result of a completed task and mark it done.

        After calling this, call claim_task again to pick up the next task.

        Args:
            task_id:    ID of the task being completed.
            found:      True if the evidence searched for was found;
                        False if the search returned no relevant results.
            summary:    One or two sentences stating what was found (or not
                        found). Factual, no interpretation.
            evidence:   List of specific data points: timestamps, event IDs,
                        usernames, IP addresses, file paths, counts, etc.
                        Empty list if nothing was found.
            assessment: Your assessment of how this result relates to the
                        hypothesis. One of:
                        "supports" — result is consistent with the hypothesis
                                     being true
                        "refutes"  — result is inconsistent with the hypothesis
                                     being true
                        "neutral"  — result is inconclusive or tangential
                        Note: you are assessing the evidence, not deciding
                        the hypothesis. The Investigator makes that call.
        """
        t = get_state().complete_task(
            task_id=task_id,
            found=found,
            summary=summary,
            evidence=evidence,
            assessment=assessment,
        )
        return {
            "id": t.id,
            "hypothesis_id": t.hypothesis_id,
            "status": t.status,
            "result": t.result,
            "completed_at": t.completed_at,
        }
