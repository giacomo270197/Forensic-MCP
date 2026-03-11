"""
mcp_tools.defender
==================
Registers two MCP tools for Windows Defender:

  run_defender_scan   — trigger a full or custom-path scan (returns job_id)
  get_defender_report — fetch threat detections from Defender's history

Both tools invoke PowerShell cmdlets from the ConfigDefender module:
  Start-MpScan          triggers the scan
  Get-MpThreatDetection retrieves recorded detections
"""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP, Context

from ._jobs import registry
from ._models import JobSubmitted
from ._runner import run_cmd_async


def register(mcp: FastMCP, tool_cfg: dict, output_dir: Path) -> None:

    # ------------------------------------------------------------------
    # Tool 1 — trigger scan
    # ------------------------------------------------------------------

    @mcp.tool(name="run_defender_scan", description=tool_cfg["description"])
    async def run_defender_scan(
        scan_type: str = "full",
        path: str = "",
        ctx: Context = None,
    ) -> JobSubmitted:
        """
        Trigger a Windows Defender scan and return immediately with a job_id.
        Poll get_job_status(job_id) to check when the scan completes.
        Then call get_defender_report() to retrieve any threats found.

        Parameters
        ----------
        scan_type:
            "full"   — full system scan (can take a long time).
            "custom" — scan a specific file or directory (requires path).
        path:
            Absolute path to scan. Required when scan_type is "custom".
        """
        if scan_type == "custom" and not path:
            return JobSubmitted(
                job_id="error",
                tool_name="run_defender_scan",
                status="failed",
                message="scan_type 'custom' requires a path argument.",
            )

        if scan_type == "custom":
            ps_script = (
                f"Start-MpScan -ScanType CustomScan -ScanPath '{path}'; "
                f"Write-Output 'Scan complete'"
            )
        else:
            ps_script = (
                "Start-MpScan -ScanType FullScan; "
                "Write-Output 'Scan complete'"
            )

        cmd = ["powershell", "-NonInteractive", "-Command", ps_script]

        async def _work():
            result = await run_cmd_async(
                cmd,
                timeout=7200,  # full scans can take hours
                progress_cb=_make_progress_cb(ctx),
            )
            return result

        job_id   = registry.submit("run_defender_scan", _work())
        scan_desc = f"custom path '{path}'" if scan_type == "custom" else "full system"

        return JobSubmitted(
            job_id=job_id,
            tool_name="run_defender_scan",
            status="pending",
            message=(
                f"Defender {scan_desc} scan started. "
                f"Poll get_job_status('{job_id}') to check progress. "
                f"Once done, call get_defender_report() to retrieve findings."
            ),
        )

    # ------------------------------------------------------------------
    # Tool 2 — fetch threat report
    # ------------------------------------------------------------------

    @mcp.tool()
    async def get_defender_report(
        since_hours: int = 24,
    ) -> dict:
        """
        Retrieve Windows Defender threat detections recorded on this machine.

        Returns structured detection records including threat name, severity,
        affected resources, detection time, and remediation status.
        Call this after a scan completes or at any time to check Defender's
        detection history.

        Parameters
        ----------
        since_hours:
            Only return detections from the last N hours (default 24).
            Pass 0 to return all recorded detections.
        """
        # Build PowerShell: get detections, filter by time, output as JSON
        if since_hours > 0:
            ps_script = (
                f"$cutoff = (Get-Date).AddHours(-{since_hours}); "
                "$detections = Get-MpThreatDetection | "
                "Where-Object { $_.InitialDetectionTime -ge $cutoff }; "
                "if ($detections) { "
                "  $detections | ForEach-Object { "
                "    $threat = Get-MpThreat -ThreatID $_.ThreatID -ErrorAction SilentlyContinue; "
                "    [PSCustomObject]@{ "
                "      ThreatName        = $threat.ThreatName; "
                "      Severity          = $threat.SeverityID; "
                "      CategoryName      = $threat.CategoryID; "
                "      DetectionTime     = $_.InitialDetectionTime; "
                "      RemediationTime   = $_.RemediationTime; "
                "      Status            = $_.CurrentThreatExecutionStatusID; "
                "      Resources         = $_.Resources -join '; '; "
                "      ProcessName       = $_.ProcessName; "
                "    } "
                "  } | ConvertTo-Json -Depth 3 "
                "} else { Write-Output '[]' }"
            )
        else:
            ps_script = (
                "$detections = Get-MpThreatDetection; "
                "if ($detections) { "
                "  $detections | ForEach-Object { "
                "    $threat = Get-MpThreat -ThreatID $_.ThreatID -ErrorAction SilentlyContinue; "
                "    [PSCustomObject]@{ "
                "      ThreatName        = $threat.ThreatName; "
                "      Severity          = $threat.SeverityID; "
                "      CategoryName      = $threat.CategoryID; "
                "      DetectionTime     = $_.InitialDetectionTime; "
                "      RemediationTime   = $_.RemediationTime; "
                "      Status            = $_.CurrentThreatExecutionStatusID; "
                "      Resources         = $_.Resources -join '; '; "
                "      ProcessName       = $_.ProcessName; "
                "    } "
                "  } | ConvertTo-Json -Depth 3 "
                "} else { Write-Output '[]' }"
            )

        cmd    = ["powershell", "-NonInteractive", "-Command", ps_script]
        result = await run_cmd_async(cmd, timeout=60)

        if not result["success"]:
            return {
                "success": False,
                "error":   result["stderr"] or "PowerShell command failed.",
            }

        import json
        from datetime import datetime, timezone

        raw = result["stdout"].strip()
        try:
            detections = json.loads(raw) if raw and raw != "[]" else []
            # Normalise: single object comes back as dict, not list
            if isinstance(detections, dict):
                detections = [detections]
        except json.JSONDecodeError:
            detections = []

        # Write report to disk
        out_dir   = output_dir / "defender"
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path  = out_dir / f"detections_{timestamp}.json"
        report    = {
            "generated_at":    timestamp,
            "since_hours":     since_hours,
            "detection_count": len(detections),
            "detections":      detections,
        }
        out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

        return {
            "success":         True,
            "since_hours":     since_hours,
            "detection_count": len(detections),
            "output_file":     str(out_path),
            "detections":      detections,
        }


def _make_progress_cb(ctx: Context):
    if ctx is None:
        return None

    async def _cb(line: str) -> None:
        await ctx.report_progress(50, 100, line.strip())

    return _cb