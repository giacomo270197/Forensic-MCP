"""
mcp_tools._jobs
===============
In-memory job registry for async background tasks.

Each tool submits a coroutine via submit() and gets back a job_id.
Claude can then poll get_job_status(job_id) until status is "done"
or "failed" — keeping every individual MCP call well within the
Claude Desktop timeout window.

Job lifecycle
-------------
  pending  →  running  →  done
                       →  failed
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    DONE     = "done"
    FAILED   = "failed"


class Job:
    def __init__(self, job_id: str, tool_name: str) -> None:
        self.job_id     = job_id
        self.tool_name  = tool_name
        self.status     = JobStatus.PENDING
        self.result:    Any = None
        self.error:     str = ""
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.started_at: str = ""
        self.finished_at: str = ""
        self._task: asyncio.Task | None = None

    def to_dict(self) -> dict:
        return {
            "job_id":      self.job_id,
            "tool_name":   self.tool_name,
            "status":      self.status.value,
            "result":      self.result,
            "error":       self.error,
            "created_at":  self.created_at,
            "started_at":  self.started_at,
            "finished_at": self.finished_at,
        }


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def submit(self, tool_name: str, coro) -> str:
        """
        Register *coro* as a background task and return the job_id immediately.

        The coroutine is scheduled on the running event loop — the caller
        returns to Claude Desktop right away without waiting for it to finish.
        """
        job_id = str(uuid.uuid4())[:8]   # short ID, easier to read in chat
        job    = Job(job_id, tool_name)
        self._jobs[job_id] = job

        async def _run() -> None:
            job.status     = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc).isoformat()
            try:
                job.result      = await coro
                job.status      = JobStatus.DONE
            except Exception as exc:  # noqa: BLE001
                job.status      = JobStatus.FAILED
                job.error       = str(exc)
            finally:
                job.finished_at = datetime.now(timezone.utc).isoformat()

        job._task = asyncio.create_task(_run())
        return job_id

    def get(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def list_all(self) -> list[dict]:
        return [j.to_dict() for j in self._jobs.values()]

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job and job._task and not job._task.done():
            job._task.cancel()
            job.status = JobStatus.FAILED
            job.error  = "Cancelled by user"
            return True
        return False


# Module-level singleton — imported by tool modules and the main server
registry = JobRegistry()