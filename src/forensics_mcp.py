"""
Forensics MCP Server
====================
Config-driven MCP server that loads tool definitions from tools.yaml and
registers each tool's implementation from the mcp_tools/ package.

Adding a new tool
-----------------
1. Add an entry to tools.yaml with name, mcp_tool, executable, description.
2. Create mcp_tools/<your_tool>.py with a register(mcp, tool_cfg, output_dir)
   function that decorates and adds the tool to the FastMCP instance.
3. Restart the server — no changes to this file needed.

Built with FastMCP (pip install fastmcp pyyaml)
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from fastmcp import FastMCP
from mcp_tools._jobs import registry as job_registry
from mcp_tools._models import JobStatusResult, JobSubmitted

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SRC_DIR     = Path(__file__).parent
SERVER_DIR  = SRC_DIR.parent
CONFIG_FILE = Path(SERVER_DIR / "tools.yaml")
TOOLS_DIR   = Path(SERVER_DIR / "tools")
OUTPUT_DIR  = Path( SERVER_DIR / ".output")
STRATEGIES_FILE  = Path( SRC_DIR/ "strategies.yaml")


# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

def _load_config(config_path: Path) -> list[dict]:
    """Parse tools.yaml and return the list of tool config dicts."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Tool config not found: {config_path}\n"
            f"Set the TOOLS_CONFIG env var or place tools.yaml next to this script."
        )
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    tools = data.get("tools", [])
    if not tools:
        raise ValueError(f"No tools defined in {config_path}")
    return tools


TOOLS_CONFIG: list[dict] = _load_config(CONFIG_FILE)

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="forensics-server",
    instructions=(
        "MCP server for digital forensics. "
        "Wraps configurable CLI tools (Zimmerman and others) and provides "
        "a Python sandbox to analyse their output. "
        "Call health_check to see available tools."
    ),
)

# ---------------------------------------------------------------------------
# Dynamic tool registration
# ---------------------------------------------------------------------------
# Each entry in tools.yaml must have a `mcp_tool` key whose value matches
# a module name inside the mcp_tools/ package (e.g. "run_evtxecmd" → evtxecmd.py).
# The module must expose register(mcp, tool_cfg, output_dir).

# Ensure mcp_tools/ is importable regardless of working directory
sys.path.insert(0, str(SERVER_DIR))

_registered: list[str] = []   # mcp_tool names successfully loaded
_failed:     list[str] = []   # mcp_tool names that failed to load

for _cfg in TOOLS_CONFIG:
    _cfg["executable"] = str(Path(SERVER_DIR / "tools" / _cfg["executable"]))
    _mcp_tool  = _cfg.get("mcp_tool", "")
    # Module name: strip "run_" prefix if present (run_evtxecmd → evtxecmd)
    _mod_name  = _cfg.get("module") or _mcp_tool.removeprefix("run_")
    _full_mod  = f"mcp_tools.{_mod_name}"
    try:
        _mod = importlib.import_module(_full_mod)
        _mod.register(mcp, _cfg, OUTPUT_DIR)
        _registered.append(_mcp_tool)
    except ModuleNotFoundError:
        print(
            f"[warn] No implementation found for '{_mcp_tool}' "
            f"(expected {_full_mod}.py) — skipping.",
            file=sys.stderr,
        )
        _failed.append(_mcp_tool)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[error] Failed to register '{_mcp_tool}': {exc}",
            file=sys.stderr,
        )
        _failed.append(_mcp_tool)

# ---------------------------------------------------------------------------
# Tool: health_check  (always present, not in tools.yaml)
# ---------------------------------------------------------------------------


@mcp.tool()
def health_check() -> dict:
    """
    Check the health of the forensics MCP server.

    Returns
    -------
    - Server status and timestamp
    - List of available tools (from tools.yaml) with description and
      whether the executable and implementation module are present
    - List of tools that failed to load
    - Python version
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    available = []
    for cfg in TOOLS_CONFIG:
        mcp_tool  = cfg.get("mcp_tool", "")
        mod_name  = cfg.get("module") or mcp_tool.removeprefix("run_")
        impl_path = SERVER_DIR / "src" / "mcp_tools" / f"{mod_name}.py"
        exe_path  = Path(cfg.get("executable", ""))

        available.append({
            "name":            cfg.get("name", mcp_tool),
            "mcp_tool":        mcp_tool,
            "description":     cfg.get("description", "").strip(),
            "executable":      str(exe_path),
            "executable_found": exe_path.exists(),
            "implementation":  str(impl_path),
            "implementation_found": impl_path.exists(),
            "loaded":          mcp_tool in _registered,
        })

    return {
        "status":          "ok" if not _failed else "degraded",
        "timestamp":       datetime.utcnow().isoformat() + "Z",
        "config_file":     str(CONFIG_FILE),
        "output_dir":      str(OUTPUT_DIR),
        "python_version":  sys.version,
        "tools_available": available,
        "tools_failed":    _failed,
    }


# ---------------------------------------------------------------------------
# Tool: run_analysis_script  (always present, not in tools.yaml)
# ---------------------------------------------------------------------------


@mcp.tool()
async def run_analysis_script(
    script: str,
    data_file: str = "",
    timeout: int = 3600,
) -> JobSubmitted:
    """
    Execute a Python analysis script against a previously parsed output file.
    Returns immediately with a job_id. Poll get_job_status(job_id) to check
    progress and retrieve results when done.

    The variable DATA_FILE is automatically injected at the top of the script
    so you can reference the parsed CSV/JSON without hardcoding the path::

        import pandas as pd
        df = pd.read_csv(DATA_FILE)
        print(df.head())

    Parameters
    ----------
    script:
        Full Python source code to execute.
    data_file:
        Absolute path to a CSV/JSON file produced by one of the tool runners.
    timeout:
        Maximum seconds to allow the script to run (default 60).
    """
    import asyncio
    import tempfile
    import traceback

    preamble    = f'DATA_FILE = r"""{data_file}"""\n\n'
    full_script = preamble + script

    async def _work():
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(full_script)
            tmp_path = tmp.name

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return {
                    "success":         False,
                    "returncode":      -1,
                    "stdout":          "",
                    "stderr":          f"Script timed out after {timeout}s",
                    "script_executed": full_script,
                }
            return {
                "success":         proc.returncode == 0,
                "returncode":      proc.returncode,
                "stdout":          stdout.decode(errors="replace").strip(),
                "stderr":          stderr.decode(errors="replace").strip(),
                "script_executed": full_script,
            }
        except Exception:  # noqa: BLE001
            return {
                "success":         False,
                "returncode":      -1,
                "stdout":          "",
                "stderr":          traceback.format_exc(),
                "script_executed": full_script,
            }
        finally:
            try:
                import os as _os
                _os.unlink(tmp_path)
            except OSError:
                pass

    job_id = job_registry.submit("run_analysis_script", _work())

    return JobSubmitted(
        job_id=job_id,
        tool_name="run_analysis_script",
        status="pending",
        message=f"Analysis script started. Poll get_job_status('{job_id}') to check progress.",
    )

# ---------------------------------------------------------------------------
# Findings tools
# ---------------------------------------------------------------------------

FINDINGS_DIR = OUTPUT_DIR / "findings"


def _ensure_findings_dir() -> Path:
    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    return FINDINGS_DIR


@mcp.tool()
def add_timeline_entry(
    time: str,
    event: str,
    evidence_source: str,
    relevance: str,
) -> dict:
    """
    Add an entry to the investigation timeline CSV.

    Call this whenever you identify a significant event during analysis.
    The timeline is stored at <output_dir>/findings/timeline.csv and
    accumulates entries across all tool calls and sessions.

    Parameters
    ----------
    time:
        Timestamp of the event in any unambiguous format
        (e.g. "2024-03-15 14:32:01 UTC", "2024-03-15T14:32:01Z").
    event:
        Short description of what happened (e.g. "cmd.exe executed by user
        Administrator", "File deleted from Desktop").
    evidence_source:
        Which artefact this came from (e.g. "Security.evtx / EventID 4688",
        "C:\\Windows\\Prefetch\\CMD.EXE-ABC123.pf").
    relevance:
        Why this event matters forensically (e.g. "Possible lateral movement",
        "Anti-forensics — deliberate deletion").
    """
    import csv

    findings_dir = _ensure_findings_dir()
    timeline_path = findings_dir / "timeline.csv"
    file_exists   = timeline_path.exists()

    with timeline_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["time", "event", "evidence_source", "relevance"])
        writer.writerow([time, event, evidence_source, relevance])

    return {
        "status":        "ok",
        "timeline_path": str(timeline_path),
        "entry": {
            "time":            time,
            "event":           event,
            "evidence_source": evidence_source,
            "relevance":       relevance,
        },
    }


@mcp.tool()
def write_finding(
    title: str,
    content: str,
    severity: str = "medium",
) -> dict:
    """
    Write a forensic finding to disk as a markdown note.

    Call this whenever you identify something significant that warrants
    documentation — anomalies, IOCs, patterns, hypotheses, or anything
    worth preserving outside the conversation context.

    Each finding is saved as a separate timestamped markdown file under
    <output_dir>/findings/notes/.

    Parameters
    ----------
    title:
        Short title for the finding (used as the filename and H1 heading).
        E.g. "Suspicious PowerShell execution at 14:32".
    content:
        Full markdown content of the finding. Can include context,
        supporting evidence, references to artefacts, and analyst notes.
    severity:
        One of "low", "medium", "high", "critical". Default "medium".
    """
    import re

    findings_dir = _ensure_findings_dir()
    notes_dir    = findings_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    timestamp   = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_title  = re.sub(r"[^\w\-]", "_", title)[:60]
    filename    = f"{timestamp}_{safe_title}.md"
    note_path   = notes_dir / filename

    md = "\n".join([
        f"# {title}",
        f"",
        f"**Severity:** {severity}  ",
        f"**Recorded:** {datetime.utcnow().isoformat()}Z",
        f"",
        "---",
        f"",
        content,
    ])

    note_path.write_text(md, encoding="utf-8")

    return {
        "status":    "ok",
        "note_path": str(note_path),
        "title":     title,
        "severity":  severity,
    }


@mcp.tool()
def summarise_findings() -> dict:
    """
    Read all timeline entries and markdown notes written so far and compile
    them into a single structured investigation report saved to disk.

    Call this when you believe the investigation is complete or at a natural
    checkpoint. The report is written to <output_dir>/findings/report.md
    and its content is returned so you can present it to the user.

    Returns the full report text and the path where it was saved.
    """
    import csv

    findings_dir = _ensure_findings_dir()

    # --- Read timeline ---
    timeline_path = findings_dir / "timeline.csv"
    timeline_rows: list[dict] = []
    if timeline_path.exists():
        with timeline_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            timeline_rows = list(reader)

    # --- Read notes ---
    notes_dir  = findings_dir / "notes"
    note_files = sorted(notes_dir.glob("*.md")) if notes_dir.exists() else []
    notes: list[dict] = []
    for nf in note_files:
        notes.append({
            "filename": nf.name,
            "content":  nf.read_text(encoding="utf-8"),
        })

    if not timeline_rows and not notes:
        return {
            "status":  "empty",
            "message": "No timeline entries or notes found. Run some tools and record findings first.",
        }

    # --- Build report ---
    now    = datetime.utcnow().isoformat() + "Z"
    lines  = [
        "# Investigation Report",
        f"",
        f"**Generated:** {now}  ",
        f"**Timeline entries:** {len(timeline_rows)}  ",
        f"**Notes:** {len(notes)}",
        "",
        "---",
        "",
    ]

    # Timeline section
    lines += [
        "## Timeline",
        "",
        "| Time | Event | Evidence Source | Relevance |",
        "|------|-------|----------------|-----------|",
    ]
    for row in timeline_rows:
        t   = row.get("time", "")
        ev  = row.get("event", "")
        src = row.get("evidence_source", "")
        rel = row.get("relevance", "")
        lines.append(f"| {t} | {ev} | {src} | {rel} |")

    lines += ["", "---", ""]

    # Notes section
    lines += ["## Analyst Notes", ""]
    for note in notes:
        lines += [note["content"], "", "---", ""]

    report = "\n".join(lines)
    report_path = findings_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")

    return {
        "status":      "ok",
        "report_path": str(report_path),
        "report":      report,
    }


# ---------------------------------------------------------------------------
# Tool: get_job_status
# ---------------------------------------------------------------------------


@mcp.tool()
def get_job_status(job_id: str) -> JobStatusResult:
    """
    Poll the status of a background job started by a parser tool.

    Call this repeatedly after run_evtxecmd / run_pecmd / run_recmd until
    status is "done" or "failed". The result field is populated on completion.

    Parameters
    ----------
    job_id:
        The job_id returned when the tool was first called.
    """
    job = job_registry.get(job_id)
    if job is None:
        return JobStatusResult(
            job_id=job_id,
            tool_name="unknown",
            status="failed",
            error=f"No job found with id '{job_id}'",
            created_at="",
            started_at="",
            finished_at="",
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
        "message":   f"Job '{job_id}' cancelled." if cancelled else f"Job '{job_id}' not found or already finished.",
    }


# ---------------------------------------------------------------------------
# Tool: fetch_strategy
# ---------------------------------------------------------------------------


@mcp.tool()
def fetch_strategy(strategy: str) -> dict:
    """
    Fetch an investigation strategy playbook by name.

    Returns step-by-step instructions for carrying out a specific type
    of forensic investigation. Call this at the start of an investigation
    to understand which tools to run and in what order.

    Available strategies (defined in strategies.yaml):
      - windows           Full Windows endpoint investigation

    Parameters
    ----------
    strategy:
        Name of the strategy to fetch. Pass an empty string to get the
        full list with descriptions at runtime (in case strategies.yaml
        has been updated since the server started).
    """
    if not STRATEGIES_FILE.exists():
        return {
            "error": f"Strategies file not found: {STRATEGIES_FILE}",
            "hint":  "Create strategies.yaml next to forensics_mcp.py.",
        }

    with STRATEGIES_FILE.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    strategies = data.get("strategies", {})

    # List mode
    if not strategy:
        return {
            "available_strategies": [
                {
                    "name":        name,
                    "description": cfg.get("description", ""),
                }
                for name, cfg in strategies.items()
            ]
        }

    # Lookup mode
    entry = strategies.get(strategy)
    if entry is None:
        return {
            "error":                f"Strategy '{strategy}' not found.",
            "available_strategies": list(strategies.keys()),
        }

    return {
        "strategy":    strategy,
        "description": entry.get("description", ""),
        "text":        entry.get("text", "").strip(),
    }

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--sse" in sys.argv:
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
