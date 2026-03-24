# Forensic MCP Server

An MCP server that orchestrates Windows digital forensics analysis using [Eric Zimmerman's tools](https://ericzimmerman.github.io/), [Hayabusa](https://github.com/Yamato-Security/hayabusa), and others. Point it at your evidence (disk image, KAPE collection, individual log files).

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)

## What it does

The server wraps 14 forensic CLI tools behind the [Model Context Protocol](https://modelcontextprotocol.io/), letting an AI agent:

- Parse execution artefacts (Prefetch, Amcache, Shimcache)
- Analyse Windows Event Logs with Hayabusa detection rules
- Extract NTFS filesystem metadata ($MFT, USN Journal)
- Mine the Registry for persistence and user activity
- Recover Jump Lists, LNK files, and Recycle Bin entries
- Query SRUM network telemetry and User Access Logging
- Run arbitrary Python analysis scripts against parsed output
- Build a consolidated timeline and structured investigation report

All tool output is auto-ingested into a SQLite database for ad-hoc querying. An async job queue keeps MCP calls non-blocking — tools run in the background and the agent polls for completion.

The tools are meant to be easy to plug in and expose via MCP so this can be extended to be a investigation companion for more than just Windows forensic tasks.

## Architecture

```
┌──────────────────────────┐
│  Claude (Orchestrator)   │
│  Spawns subagents as     │
│  needed                  │
└─────────┬────────────────┘
          │ MCP (stdio or SSE)
┌─────────▼────────────────┐     
│   Forensic MCP Server    │   
│  ┌──────────────────────┐│
│  │ tools.yaml (config)  ││
│  ├──────────────────────┤│
│  │ Async Job Queue      ││
│  │ SQLite Ingestion     ││
│  │ Investigation Plan   ││
│  │ Q&A Blackboard       ││
│  │ Findings & Timeline  │| 
│  └──────────┬───────────┘│
└─────────────┼────────────┘
              │ subprocess
   ┌──────────▼──────────┐
   │  Zimmerman Tools    │
   │  Hayabusa           |
   |  ...                │
   └─────────────────────┘
```
Questions are the end goals of this investigation. They are defined by the
user before the investigation begins and do not change during it. 

The Investigator agent is responsible for generating an investigation plan, come up with Hypothesis to answer Questions posed by the user, and create specific Tasks to validate such Hypothesis. The Investigator never queries data itself, be it raw evidence, CSV/JSON outputs, or even the SQLite database.

A Tasks queue exist for the Investigator to submit Tasks to Workers subagents. Each Worker fetches Tasks meant for it, runs the required anaysis against the parsed data, and submit answers.

This **context isolation** pattern keeps the main conversation focused on investigation logic and helps preventing the LLM running into a greedy "parsing" mode.

## Quick start

### Prerequisites

- Python 3.10+
- Windows (the wrapped forensic tools are Windows executables)

### Install

```bash
pip install -r requirements.txt
```

### Run

**SSE mode** (HTTP, for testing or remote clients, Preferred):
```bash
python src/forensics_mcp.py --sse
# Listening on http://127.0.0.1:8000/sse
```

**stdio mode** (for Claude Desktop / Claude Code):
```bash
python src/forensics_mcp.py
```

### Configure Claude CLI/Desktop

**SSE mode**
```
claude mcp add --transport sse myserver http://127.0.0.1:8000/sse
```

**Claude Desktop configuration (stdio mode)**

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "forensics": {
      "command": "python",
      "args": ["path/to/src/forensics_mcp.py"]
    }
  }
}
```

## Available tools

### Forensic parsers

| Tool | Artefact | Forensic value |
|------|----------|----------------|
| `run_hayabusa` | .evtx files | Event log timeline with detection rules |
| `run_pecmd` | Prefetch (.pf) | Program execution history, run counts |
| `run_amcacheparser` | Amcache.hve | Application execution, SHA1 hashes |
| `run_appcompatcacheparser` | SYSTEM hive | Shimcache execution history |
| `run_recmd` | Registry hives | Persistence, user activity, configuration |
| `run_sbecmd` | UsrClass.dat | Shell bag folder access history |
| `run_jlecmd` | Jump Lists | Recently/frequently accessed files |
| `run_lecmd` | .lnk files | Shortcut target paths, timestamps |
| `run_mftecmd` | $MFT, $J, $Boot | Filesystem metadata, deleted files |
| `run_rbcmd` | Recycle Bin $I files | Deleted file recovery |
| `run_recentfilecacheparser` | RecentFileCache.bcf | Legacy execution evidence (XP–7) |
| `run_srumecmd` | SRUDB.dat | Network usage, app resource telemetry |
| `run_sumecmd` | SUM directory | Remote access logs (Server only) |

### Composite

| Tool | Description |
|------|-------------|
| `windows_full_disk` | Runs all parsers meant for Windows disk images in parallel against a mounted disk image |

### Analysis & reporting

| Tool | Description |
|------|-------------|
| `run_analysis_script` | Execute Python code against parsed output files |
| `add_timeline_entry` | Append event to the investigation timeline |
| `write_finding` | Save a markdown finding with severity level |
| `summarise_findings` | Compile timeline + notes into a final report |

### Database

| Tool | Description |
|------|-------------|
| `list_tables` | Show SQLite tables and row counts |
| `get_table_columns` | Inspect table schema |
| `query_table` | Run SELECT queries (max 20 rows) |

### Investigation management

| Tool | Description |
|------|-------------|
| `health_check` | Verify all tool binaries are present |
| `create_hypothesis` | Create a hypothesis to investigate |
| `list_hypotheses` | List all hypotheses and their status |
| `update_hypothesis` | Update a hypothesis with new findings |
| `create_task` | Submit a task to the worker queue |
| `claim_task` | Claim a pending task for processing |
| `complete_task` | Mark a task as completed with results |
| `get_pending_review` | Retrieve tasks awaiting review |
| `open_task_queue` | Open the task queue for workers |
| `close_task_queue` | Close the task queue |
| `list_jobs` | List all background jobs |
| `get_job_status` | Check the status of a background job |
| `cancel_job` | Cancel a running background job |

## Adding a new tool

1. Add an entry to `tools.yaml`:
   ```yaml
   - name: MyTool
     mcp_tool: run_mytool
     executable: "path/to/executable" # If one exists
     description: What it does
   ```
2. Add the implementation to `src/mcp_tools/tools.py` inside `build_tool_registry()`
3. Restart the server

## Output structure

After running an investigation, `.output/` contains:

```
.output/
├── database.db              # SQLite with all parsed data
├── findings/
│   ├── timeline.csv         # Consolidated event timeline
│   ├── notes/               # Markdown findings by severity
│   └── report.md            # Final investigation report
├── hayabusa/                # Event log CSVs
├── pecmd/                   # Prefetch CSVs
├── recmd/                   # Registry CSVs
└── ...                      # One directory per tool
```

## Example output

See [`Examples/Reports/cfreds_2022_red_petya.md`](Examples/Reports/cfreds_2022_red_petya.md) for a full investigation report from a ransomware case, including attack timeline, IOCs, and MITRE ATT&CK mapping. [`Examples/Reports/cfreds_2022_red_petya_follow_up_questions.md`](Examples/Reports/cfreds_2022_red_petya_follow_up_questions.md) is a report for the same incident, but with data appended after follow up questions regarding the malware executables and IOCs. 

## Prompts

See [`Examples/LLM Prompts`](`Examples/LLM_Prompts) for examples of different prompting to explain the LLM how it should perform its work. Please note these are tested with Claude Code.   
The server should be able to perform a wide variety of forensic tasks. Different explanation prompts might be needed to tackle different problems (eg. Windows Server full disk analysis vs GitHub audit logs review).    
I aim at providing templates, at least, for the most common tasks an analyst might run into.

## Tests

```bash
# Start the server
cd src && python forensics_mcp.py --sse &

# Run tests
cd test && pytest
```

Tests cover health checks, findings/timeline writing, investigation plan lifecycle, question routing, SQLite queries, and job management.

## License

This project wraps third-party forensic tools that have their own licenses:
- [Eric Zimmerman's tools](https://ericzimmerman.github.io/) — MIT License
- [Hayabusa](https://github.com/Yamato-Security/hayabusa) — GPL-3.0
