# ---------------------------------------------------------------------------
# Findings tools
# ---------------------------------------------------------------------------

from datetime import datetime
from pathlib import Path

def register_tools(mcp, output_dir):

    FINDINGS_DIR = output_dir / "findings"

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
            Short description of what happened.
        evidence_source:
            Which artefact this came from.
        relevance:
            Why this event matters forensically.
        """
        import csv

        findings_dir  = _ensure_findings_dir()
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

        Each finding is saved as a separate timestamped markdown file under
        <output_dir>/findings/notes/.

        Parameters
        ----------
        title:
            Short title for the finding (used as the filename and H1 heading).
        content:
            Full markdown content of the finding.
        severity:
            One of "low", "medium", "high", "critical". Default "medium".
        """
        import re

        findings_dir = _ensure_findings_dir()
        notes_dir    = findings_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        timestamp  = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        safe_title = re.sub(r"[^\w\-]", "_", title)[:60]
        note_path  = notes_dir / f"{timestamp}_{safe_title}.md"

        md = "\n".join([
            f"# {title}", "",
            f"**Severity:** {severity}  ",
            f"**Recorded:** {datetime.utcnow().isoformat()}Z", "",
            "---", "",
            content,
        ])
        note_path.write_text(md, encoding="utf-8")

        return {"status": "ok", "note_path": str(note_path), "title": title, "severity": severity}


    @mcp.tool()
    def summarise_findings() -> dict:
        """
        Read all timeline entries and markdown notes written so far and compile
        them into a single structured investigation report saved to disk.

        The report is written to <output_dir>/findings/report.md.
        Returns the full report text and the path where it was saved.
        """
        import csv

        findings_dir = _ensure_findings_dir()

        timeline_path = findings_dir / "timeline.csv"
        timeline_rows: list[dict] = []
        if timeline_path.exists():
            with timeline_path.open(encoding="utf-8") as f:
                timeline_rows = list(csv.DictReader(f))

        notes_dir  = findings_dir / "notes"
        note_files = sorted(notes_dir.glob("*.md")) if notes_dir.exists() else []
        notes      = [{"filename": nf.name, "content": nf.read_text(encoding="utf-8")}
                    for nf in note_files]

        if not timeline_rows and not notes:
            return {
                "status":  "empty",
                "message": "No timeline entries or notes found. Run some tools and record findings first.",
            }

        now   = datetime.utcnow().isoformat() + "Z"
        lines = [
            "# Investigation Report", "",
            f"**Generated:** {now}  ",
            f"**Timeline entries:** {len(timeline_rows)}  ",
            f"**Notes:** {len(notes)}", "",
            "---", "",
            "## Timeline", "",
            "| Time | Event | Evidence Source | Relevance |",
            "|------|-------|----------------|-----------|",
        ]
        for row in timeline_rows:
            lines.append(
                f"| {row.get('time','')} | {row.get('event','')} "
                f"| {row.get('evidence_source','')} | {row.get('relevance','')} |"
            )
        lines += ["", "---", "", "## Analyst Notes", ""]
        for note in notes:
            lines += [note["content"], "", "---", ""]

        report      = "\n".join(lines)
        report_path = findings_dir / "report.md"
        report_path.write_text(report, encoding="utf-8")

        return {"status": "ok", "report_path": str(report_path), "report": report}