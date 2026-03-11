# ------------------------------------------------------------------ #
# Question / Answer blackboard                                        #
# ------------------------------------------------------------------ #

from ._questions import question_queue

_PARSER_ROLES = {
    "Prefetch", "Amcache", "AppCompatCache", "EVTX",
    "MFT", "UsnJrnl", "Registry", "ShellBags",
    "JumpLists", "LNK", "RecycleBin", "SRUM",
    "RecentFileCache", "Defender",
}

def register_tools(mcp, output_dir):

    @mcp.tool()
    def submit_question(
        text:           str,
        hypothesis:     str,
        evidence_hints: list[str],
        priority:       int = 3,
        parent_id:      str = "",
    ) -> dict:
        """
        Submit an investigative question directly to the parser agent
        responsible for the first artefact in evidence_hints.

        For questions that span multiple artefacts, call submit_question
        once per artefact with the same parent_id. Then poll
        check_children(parent_id) until all are answered and coalesce
        the answers yourself.

        Parameters
        ----------
        text:
            The question. Be specific — name the artefact, time window,
            user account, or file path relevant to the hypothesis.
        hypothesis:
            The broader hypothesis this question is testing.
        evidence_hints:
            Ordered list of artefact types. The FIRST entry determines
            which parser agent receives this question.
            Valid values: Prefetch, Amcache, AppCompatCache, EVTX,
            MFT, UsnJrnl, Registry, ShellBags, JumpLists, LNK,
            RecycleBin, SRUM, RecentFileCache, Defender
        priority:
            1=critical, 3=normal (default), 5=low
        parent_id:
            Optional. Set the same parent_id on multiple questions to
            group them for coalescing via check_children().
        """
        if not evidence_hints:
            return {
                "success": False,
                "error":   "evidence_hints must contain at least one artefact.",
                "valid_artefacts": sorted(_PARSER_ROLES),
            }

        artefact = evidence_hints[0]
        if artefact not in _PARSER_ROLES:
            return {
                "success": False,
                "error":   f"Unknown artefact '{artefact}' in evidence_hints.",
                "valid_artefacts": sorted(_PARSER_ROLES),
            }

        assigned_role = f"parser:{artefact}"
        q = question_queue.submit(
            text           = text,
            hypothesis     = hypothesis,
            evidence_hints = evidence_hints,
            priority       = priority,
            depth          = 0,
            assigned_role  = assigned_role,
            output_dir     = output_dir,
            parent_id      = parent_id or None,
        )
        return {
            "question_id":   q.question_id,
            "assigned_role": q.assigned_role,
            "parent_id":     q.parent_id,
            "status":        q.status,
            "message": (
                f"Question '{q.question_id}' queued for {assigned_role}. "
                + (
                    f"Group parent_id='{q.parent_id}' has "
                    f"{len(question_queue.list_all(output_dir, parent_id=q.parent_id))} "
                    f"question(s). Call check_children('{q.parent_id}') to monitor."
                    if q.parent_id else
                    "Call list_questions(status='answered') to read the answer."
                )
            ),
        }

    @mcp.tool()
    def get_next_question(agent_role: str) -> dict:
        """
        Claim the next pending question assigned to your agent role.
        Only questions with matching assigned_role are returned.

        Parameters
        ----------
        agent_role:
            Your role. Must match exactly the assigned_role on the question.
            Parser agents use: "parser:Prefetch", "parser:EVTX", etc.

        Returns {"empty": true} if no questions are pending for your role.
        """
        q = question_queue.get_next_pending(agent_role, output_dir)
        if q is None:
            count = question_queue.pending_count(output_dir, agent_role)
            return {
                "empty":            True,
                "agent_role":       agent_role,
                "pending_for_role": count,
                "message":          f"No pending questions for role '{agent_role}'.",
            }
        return {
            "question_id":    q.question_id,
            "text":           q.text,
            "hypothesis":     q.hypothesis,
            "evidence_hints": q.evidence_hints,
            "priority":       q.priority,
            "parent_id":      q.parent_id,
            "assigned_role":  q.assigned_role,
            "status":         q.status,
            "message": (
                f"Question '{q.question_id}' claimed. "
                f"Call submit_answer('{q.question_id}', ...) when done."
            ),
        }

    @mcp.tool()
    def submit_answer(
        question_id:   str,
        answer:        str,
        confirmed:     bool,
        evidence_refs: list[str],
        iocs:          list[dict],
    ) -> dict:
        """
        Record the answer to a claimed question.

        Keep the answer concise — one or two sentences. Full detail goes
        in evidence_refs.

        Parameters
        ----------
        question_id:   The ID returned by get_next_question().
        answer:        One or two sentence finding.
        confirmed:     True if evidence confirmed the hypothesis.
        evidence_refs: File paths or table/row references.
        """
        q = question_queue.get(question_id, output_dir)
        q.answer_question(
            answer = answer,
            detail = {
                "confirmed":     confirmed,
                "evidence_refs": evidence_refs,
                "iocs":          iocs,
            },
        )
        return {
            "success":       True,
            "question_id":   question_id,
            "parent_id":     q.parent_id,
            "status":        q.status,
            "message": (
                f"Answer recorded."
                + (
                    f"Interviewer: call check_children('{q.parent_id}') "
                    "to see if all siblings are done."
                    if q.parent_id else
                    "Interviewer: call list_questions(status='answered') to read it."
                )
            ),
        }

    @mcp.tool()
    def get_question(question_id: str) -> dict:
        """
        Return the full detail of a single question including answer_detail
        (evidence_refs and iocs). Used by the Interviewer to read all
        sibling answers before coalescing into a summary finding.
        """
        q = question_queue.get(question_id, output_dir)
        if q is None:
            return {"found": False, "error": f"Question '{question_id}' not found."}
        return {"found": True, **q.to_dict()}


    @mcp.tool()
    def check_children(parent_id: str) -> dict:
        """
        Check whether all questions submitted with a given parent_id are
        answered or failed. Used by the Interviewer to know when it can
        coalesce answers.

        When ready=true, call get_question(<child_id>) for each child
        to read the full answers, then write a consolidated finding.
        """
        all_done = question_queue.all_children_answered(parent_id, output_dir)
        children = question_queue.list_all(output_dir, parent_id=parent_id)
        answered = sum(1 for c in children if c["status"] == "answered")
        failed   = sum(1 for c in children if c["status"] == "failed")
        pending  = sum(1 for c in children if c["status"] in ("pending", "in_progress"))
        return {
            "parent_id": parent_id,
            "ready":     all_done,
            "total":     len(children),
            "answered":  answered,
            "failed":    failed,
            "pending":   pending,
            "message": (
                "All questions in this group are resolved — ready to coalesce."
                if all_done else
                f"{pending} question(s) still pending."
            ),
        }