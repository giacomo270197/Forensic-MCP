from mcp_tools._models import JobStatusResult
from mcp_tools._jobs import registry as job_registry

def register_tools(mcp):

    # ---------------------------------------------------------------------------
    # Tool: get_job_status
    # ---------------------------------------------------------------------------


    @mcp.tool()
    def get_job_status(job_id: str) -> JobStatusResult:
        """
        Poll the status of a background job started by a parser tool.

        Call this repeatedly after any run_* tool until status is "done" or
        "failed". The result field is populated on completion.

        Parameters
        ----------
        job_id:
            The job_id returned when the tool was first called.
        """
        job = job_registry.get(job_id)
        if job is None:
            return JobStatusResult(
                job_id=job_id, tool_name="unknown", status="failed",
                error=f"No job found with id '{job_id}'",
                created_at="", started_at="", finished_at="",
            )
        return JobStatusResult(**job)


    # ---------------------------------------------------------------------------
    # Tool: list_jobs
    # ---------------------------------------------------------------------------


    @mcp.tool()
    def list_jobs() -> list[JobStatusResult]:
        """
        List all jobs submitted in this server session with their current status.
        Useful for checking whether any previously started parsers are still running.
        """
        return [JobStatusResult(**j) for j in job_registry.list_all()]


    # ---------------------------------------------------------------------------
    # Tool: cancel_job
    # ---------------------------------------------------------------------------


    @mcp.tool()
    def cancel_job(job_id: str) -> dict:
        """
        Cancel a running or pending background job.

        Parameters
        ----------
        job_id:
            The job_id to cancel.
        """
        cancelled = job_registry.cancel(job_id)
        return {
            "job_id":    job_id,
            "cancelled": cancelled,
            "message": (
                f"Job '{job_id}' cancelled." if cancelled
                else f"Job '{job_id}' not found or already finished."
            ),
        }