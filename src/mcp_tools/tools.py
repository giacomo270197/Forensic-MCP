"""
mcp_tools.tools
===============
All forensic tool implementations in one place.

Call build_tool_registry(tools_config, output_dir) to get a FastMCP
sub-server pre-loaded with every tool, then mount it onto the main server:

    from mcp_tools.tools import build_tool_registry

    registry = build_tool_registry(TOOLS_CONFIG, OUTPUT_DIR)
    mcp.mount(registry)
"""

from __future__ import annotations

import json
import sqlite3, os
from datetime import datetime, timezone
from pathlib import Path
from fastmcp import Context, FastMCP
import pandas as pd

from ._jobs import registry as job_registry
from ._models import JobSubmitted
from ._questions import question_queue
from ._runner import run_cmd_async
from ._utils import infer_create_table_from_csv, remove_prefix_timestamp


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _progress_cb(ctx: Context):
    """Return an async stderr-line callback, or None when ctx is absent."""
    if ctx is None:
        return None

    async def _cb(line: str) -> None:
        await ctx.report_progress(50, 100, line.strip())

    return _cb


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def register_tools(mcp, output_dir, tools_config, tools_dir) -> FastMCP:

# ------------------------------------------------------------------ #
# Hayabusa                                                            #
# ------------------------------------------------------------------ #

    def csv_to_sqlite(out_dir):
        conn = sqlite3.connect( str(output_dir / 'database.db'))
        print(conn)
        cursor = conn.cursor()
        print(cursor)
        tables = []
        for file in os.listdir(str(out_dir)):
            if file.endswith(".csv"):
                print(file)
                table_name = remove_prefix_timestamp(file)
                tables.append(table_name)
                create_table = infer_create_table_from_csv(str(out_dir / file), table_name=table_name)
                print(create_table)
                cursor.execute(create_table)
                df = pd.read_csv(str(out_dir / file))
                df.to_sql(table_name, conn, if_exists='replace', index = False)
                print(tables)
        return tables

    @mcp.tool(name="run_hayabusa")
    async def run_hayabusa(
        path: str
    ) -> JobSubmitted:
        """
        Run Hayabusa against a Windows Event Log (.evtx) file or directory.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to a directory of .evtx files.
        """
        out_dir = output_dir / "hayabusa"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "Hayabusa"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe), "csv-timeline", "-d",
            path, "-w", "-U", "-o", str(out_dir / "evtx_hayabusa.csv")
        ]
        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_hayabusa", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_hayabusa", status="pending",
            message=f"Hayabusa started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# PECmd — Prefetch                                                    #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_pecmd")
    async def run_pecmd(
        path: str,
    ) -> JobSubmitted:
        """
        Run PECmd against a Windows Prefetch (.pf) file or directory.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to a .pf file or a directory of Prefetch files.
        """
        out_dir = output_dir / "pecmd"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "PECmd"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe),
            "-f" if Path(path).is_file() else "-d", path,
            "--csv", str(out_dir)
        ]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_pecmd", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_pecmd", status="pending",
            message=f"PECmd started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# RECmd — Registry                                                    #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_recmd")
    async def run_recmd(
        path: str,
        hive: str = "",
        batch_file: str = ""
    ) -> JobSubmitted:
        """
        Run RECmd against a Windows Registry hive file or directory.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to a hive file or a directory of hive files.
        hive:
            Optional hive name hint (e.g. "NTUSER.DAT", "SAM", "SYSTEM").
        batch_file:
            Path to a RECmd batch (.reb) file defining keys/values to extract.
        """
        out_dir = output_dir / "recmd"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "RECmd"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [str(_exe), "-f" if Path(path).is_file() else "-d", path]
        if hive:
            cmd += ["--hive", hive]
        if batch_file:
            cmd += ["--bn", batch_file]
        cmd += ["--csv", str(out_dir)]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_recmd", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_recmd", status="pending",
            message=f"RECmd started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# AmcacheParser                                                       #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_amcacheparser")
    async def run_amcacheparser(
        path: str
    ) -> JobSubmitted:
        """
        Run AmcacheParser against an Amcache.hve file.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to Amcache.hve (typically
            C:\\Windows\\appcompat\\Programs\\Amcache.hve).
        """
        out_dir = output_dir / "amcacheparser"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "AmcacheParser"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe), "-f", path,
            "--csv", str(out_dir),
        ]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_amcacheparser", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_amcacheparser", status="pending",
            message=f"AmcacheParser started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# AppCompatCacheParser — Shimcache                                    #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_appcompatcacheparser")
    async def run_appcompatcacheparser(
        path: str,
    ) -> JobSubmitted:
        """
        Run AppCompatCacheParser against a SYSTEM registry hive to extract
        Shimcache (AppCompatCache) entries.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to a SYSTEM registry hive file.
        """
        out_dir = output_dir / "appcompatcacheparser"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "AppCompatCacheParser"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe), "-f", path,
            "--csv", str(out_dir),
        ]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_appcompatcacheparser", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_appcompatcacheparser", status="pending",
            message=f"AppCompatCacheParser started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# JLECmd — Jump Lists                                                 #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_jlecmd")
    async def run_jlecmd(
        path: str,
        output_format: str = "csv"
    ) -> JobSubmitted:
        """
        Run JLECmd against a Jump List file or directory.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to a .automaticDestinations-ms or
            .customDestinations-ms file, or a directory containing them.
        """
        out_dir = output_dir / "jlecmd"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "JLECmd"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe),
            "-f" if Path(path).is_file() else "-d", path,
            "--csv", str(out_dir)
        ]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_jlecmd", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_jlecmd", status="pending",
            message=f"JLECmd started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# LECmd — LNK shortcuts                                               #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_lecmd")
    async def run_lecmd(
        path: str
    ) -> JobSubmitted:
        """
        Run LECmd against a Windows LNK (.lnk) shortcut file or directory.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to a .lnk file or a directory of .lnk files.
        """
        out_dir = output_dir / "lecmd"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "LECmd"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe),
            "-f" if Path(path).is_file() else "-d", path,
            "--csv", str(out_dir)
        ]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_lecmd", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_lecmd", status="pending",
            message=f"LECmd started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# MFTECmd — NTFS artefacts                                           #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_mftecmd")
    async def run_mftecmd(
        path: str
    ) -> JobSubmitted:
        """
        Run MFTECmd against an NTFS artefact file ($MFT, $Boot, $J,
        $LogFile, $SDS, or $I30) to extract filesystem metadata.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to an NTFS artefact file (e.g. C:\\Evidence\\$MFT).
        """
        out_dir = output_dir / "mftecmd"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "MFTECmd"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe), "-f", path,
            "--csv", str(out_dir)
        ]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_mftecmd", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_mftecmd", status="pending",
            message=f"MFTECmd started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# RBCmd — Recycle Bin                                                 #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_rbcmd")
    async def run_rbcmd(
        path: str
    ) -> JobSubmitted:
        """
        Run RBCmd against a Windows Recycle Bin $I file or directory
        to recover deleted file metadata.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to a $I file or a directory containing $I files
            (e.g. C:\\$Recycle.Bin\\<SID>).
        """
        out_dir = output_dir / "rbcmd"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "RBCmd"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe),
            "-f" if Path(path).is_file() else "-d", path,
            "--csv", str(out_dir),
        ]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_rbcmd", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_rbcmd", status="pending",
            message=f"RBCmd started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# RecentFileCacheParser                                               #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_recentfilecacheparser")
    async def run_recentfilecacheparser(
        path: str
    ) -> JobSubmitted:
        """
        Run RecentFileCacheParser against a RecentFileCache.bcf file to
        extract program execution evidence from Windows XP/Vista/7 systems.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to RecentFileCache.bcf (typically
            C:\\Windows\\AppCompat\\Programs\\RecentFileCache.bcf).
        """
        out_dir = output_dir / "recentfilecacheparser"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "RecentFileCacheParser"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe), "-f", path,
            "--csv", str(out_dir)
        ]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_recentfilecacheparser", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_recentfilecacheparser", status="pending",
            message=f"RecentFileCacheParser started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# SBECmd — Shell Bags                                                 #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_sbecmd")
    async def run_sbecmd(
        path: str,
    ) -> JobSubmitted:
        """
        Run SBECmd against a UsrClass.dat hive to recover folder access
        and navigation history.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to a UsrClass.dat hive or directory of Shell
            Bag hive files.
        """
        out_dir = output_dir / "sbecmd"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "SBECmd"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe), "-d", path,
            "--csv", str(out_dir)
        ]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_sbecmd", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_sbecmd", status="pending",
            message=f"SBECmd started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# SrumECmd — SRUM                                                     #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_srumecmd")
    async def run_srumecmd(
        path: str,
        software_hive: str = "",
    ) -> JobSubmitted:
        """
        Run SrumECmd against a SRUM database (SRUDB.dat).
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to SRUDB.dat (typically
            C:\\Windows\\System32\\sru\\SRUDB.dat).
        software_hive:
            Optional path to the SOFTWARE registry hive to resolve
            application names.
        """
        out_dir = output_dir / "srumecmd"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "SrumECmd"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [str(_exe), "-f", path]
        if software_hive:
            cmd += ["--r", software_hive]
        cmd += ["--csv", str(out_dir)]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_srumecmd", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_srumecmd", status="pending",
            message=f"SrumECmd started. Poll get_job_status('{job_id}') to check progress.",
        )

# ------------------------------------------------------------------ #
# SumECmd — UAL / Windows Server                                      #
# ------------------------------------------------------------------ #

    @mcp.tool(name="run_sumecmd")
    async def run_sumecmd(
        path: str
    ) -> JobSubmitted:
        """
        Run SumECmd against a Windows User Access Logging (UAL) database
        directory to extract remote access and service usage records.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        path:
            Absolute path to a directory containing UAL .mdb files
            (typically C:\\Windows\\System32\\LogFiles\\SUM).
        """
        out_dir = output_dir / "sumecmd"
        _exe = tools_dir / [x for x in tools_config if x.get("name") == "SumECmd"][0]["executable"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_exe), "-d", path,
            "--csv", str(out_dir)
        ]

        async def _work():
            result = await run_cmd_async(cmd)
            tables = csv_to_sqlite(out_dir)
            result["created_tables"] = tables
            return result

        job_id = job_registry.submit("run_sumecmd", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="run_sumecmd", status="pending",
            message=f"SumECmd started. Poll get_job_status('{job_id}') to check progress.",
        )