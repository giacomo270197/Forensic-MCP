import asyncio
import os
import sqlite3
from pathlib import Path

import pandas as pd
from fastmcp import FastMCP

from ._jobs import registry as job_registry
from ._models import JobSubmitted
from ._runner import run_cmd_async
from ._utils import infer_create_table_from_csv, remove_prefix_timestamp


def register_tools(mcp, output_dir, tools_config, tools_dir) -> FastMCP:

    def _get_exe(name: str) -> Path:
        return tools_dir / [x for x in tools_config if x.get("name") == name][0]["executable"]

    def _csv_to_sqlite(out_dir: Path) -> list[str]:
        conn = sqlite3.connect(str(output_dir / "database.db"))
        cursor = conn.cursor()
        tables = []
        for file in os.listdir(str(out_dir)):
            if file.endswith(".csv"):
                table_name = remove_prefix_timestamp(file)
                tables.append(table_name)
                create_table = infer_create_table_from_csv(str(out_dir / file), table_name=table_name)
                cursor.execute(create_table)
                df = pd.read_csv(str(out_dir / file))
                df.to_sql(table_name, conn, if_exists="replace", index=False)
        conn.close()
        return tables

    async def _run_tool(tool_name: str, cmd: list[str], out_dir: Path) -> dict:
        result = await run_cmd_async(cmd)
        try:
            tables = _csv_to_sqlite(out_dir)
            result["created_tables"] = tables
        except Exception as exc:
            result["created_tables"] = []
            result["csv_to_sqlite_error"] = str(exc)
        return {tool_name: result}

    @mcp.tool(name="windows_full_disk")
    async def windows_full_disk(path: str) -> JobSubmitted:
        """
        Run every forensic parsing tool against a Windows evidence directory in
        parallel and wait for all of them to complete as a single composite job.

        Returns immediately with one job_id. Poll get_job_status(job_id) to
        check overall progress; individual sub-tool job IDs are not exposed.

        Parameters
        ----------
        path:
            Disk image mount point (eg. E:/).
        """

        async def _work() -> dict:
            subtasks: dict[str, asyncio.Task] = {}

            # Hayabusa -------------------------------------------------------
            out = output_dir / "hayabusa"
            out.mkdir(parents=True, exist_ok=True)
            subtasks["run_hayabusa"] = asyncio.create_task(_run_tool(
                "run_hayabusa",
                [str(_get_exe("Hayabusa")), "csv-timeline", "-d", str(Path(path / "Windows/Sytem32/winevt/Logs")),
                 "-w", "-U", "-o", str(out / "evtx_hayabusa.csv")],
                out,
            ))

            # PECmd ----------------------------------------------------------
            out = output_dir / "pecmd"
            out.mkdir(parents=True, exist_ok=True)
            subtasks["run_pecmd"] = asyncio.create_task(_run_tool(
                "run_pecmd",
                [str(_get_exe("PECmd")),
                 "-f" if Path(path).is_file() else "-d", str(Path(path / "Windows/Prefetch")),
                 "--csv", str(out)],
                out,
            ))

            # RECmd ----------------------------------------------------------
            # Each invocation gets its own subdirectory so _csv_to_sqlite
            # only ingests that invocation's CSVs, avoiding double-ingest.
            recmd_exe = str(_get_exe("RECmd"))
            recmd_base = output_dir / "recmd"
            recmd_base.mkdir(parents=True, exist_ok=True)

            # System hives (SOFTWARE, SYSTEM, SECURITY, SAM)
            sys_hives_out = recmd_base / "system_hives"
            sys_hives_out.mkdir(parents=True, exist_ok=True)
            subtasks["run_recmd_system"] = asyncio.create_task(_run_tool(
                "run_recmd_system",
                [recmd_exe, "-d", str(Path(path) / "Windows/System32/config"),
                 "--csv", str(sys_hives_out)],
                sys_hives_out,
            ))

            # Per-user hives: NTUSER.DAT and UsrClass.dat
            _skip_profiles = {"public", "default", "default user", "all users"}
            users_dir = Path(path) / "Users"
            if users_dir.exists():
                for user_dir in users_dir.iterdir():
                    if not user_dir.is_dir() or user_dir.name.lower() in _skip_profiles:
                        continue
                    username = user_dir.name

                    ntuser = user_dir / "NTUSER.DAT"
                    if ntuser.exists():
                        key = f"run_recmd_NTUSER_{username}"
                        u_out = recmd_base / f"NTUSER_{username}"
                        u_out.mkdir(parents=True, exist_ok=True)
                        subtasks[key] = asyncio.create_task(_run_tool(
                            key,
                            [recmd_exe, "-f", str(ntuser), "--csv", str(u_out)],
                            u_out,
                        ))

                    usrclass = user_dir / "AppData/Local/Microsoft/Windows/UsrClass.dat"
                    if usrclass.exists():
                        key = f"run_recmd_UsrClass_{username}"
                        u_out = recmd_base / f"UsrClass_{username}"
                        u_out.mkdir(parents=True, exist_ok=True)
                        subtasks[key] = asyncio.create_task(_run_tool(
                            key,
                            [recmd_exe, "-f", str(usrclass), "--csv", str(u_out)],
                            u_out,
                        ))

            # AmcacheParser --------------------------------------------------
            out = output_dir / "amcacheparser"
            out.mkdir(parents=True, exist_ok=True)
            subtasks["run_amcacheparser"] = asyncio.create_task(_run_tool(
                "run_amcacheparser",
                [str(_get_exe("AmcacheParser")), "-f", str(Path(path / "Windows/AppCompat/Programs/Amcache.hve")),
                 "--csv", str(out)],
                out,
            ))

            # AppCompatCacheParser -------------------------------------------
            out = output_dir / "appcompatcacheparser"
            out.mkdir(parents=True, exist_ok=True)
            subtasks["run_appcompatcacheparser"] = asyncio.create_task(_run_tool(
                "run_appcompatcacheparser",
                [str(_get_exe("AppCompatCacheParser")), "-f", str(Path(path / "Windows/System32/config/SYSTEM")),
                 "--csv", str(out)],
                out,
            ))

            # JLECmd ---------------------------------------------------------
            jlecmd_exe = str(_get_exe("JLECmd"))
            jlecmd_base = output_dir / "jlecmd"
            jlecmd_base.mkdir(parents=True, exist_ok=True)

            if users_dir.exists():
                for user_dir in users_dir.iterdir():
                    if not user_dir.is_dir() or user_dir.name.lower() in _skip_profiles:
                        continue
                    username = user_dir.name
                    recent_dir = user_dir / "AppData/Roaming/Microsoft/Windows/Recent"
                    if recent_dir.exists():
                        key = f"run_jlecmd_{username}"
                        u_out = jlecmd_base / username
                        u_out.mkdir(parents=True, exist_ok=True)
                        subtasks[key] = asyncio.create_task(_run_tool(
                            key,
                            [jlecmd_exe, "-d", str(recent_dir), "--csv", str(u_out)],
                            u_out,
                        ))

            # LECmd ----------------------------------------------------------
            out = output_dir / "lecmd"
            out.mkdir(parents=True, exist_ok=True)
            subtasks["run_lecmd"] = asyncio.create_task(_run_tool(
                "run_lecmd",
                [str(_get_exe("LECmd")),
                 "-f" if Path(path).is_file() else "-d", path,
                 "--csv", str(out)],
                out,
            ))

            # MFTECmd --------------------------------------------------------
            # Extraction must complete before parsing, so this runs as one
            # sequential coroutine rather than parallel subtasks.
            async def _mft_work() -> dict:
                mft_out = output_dir / "mftecmd"
                mft_out.mkdir(parents=True, exist_ok=True)
                extract_dir = mft_out / "extracted"
                extract_dir.mkdir(parents=True, exist_ok=True)

                mftecmd_exe = str(_get_exe("MFTECmd"))
                rawcopy_exe  = str(tools_dir / "RawCopy.exe")
                usnjrnl_exe  = str(tools_dir / "ExtractUsnJrnl.exe")
                drive = Path(path).drive   # e.g. "E:"

                inner: dict = {}

                # -- $MFT ----------------------------------------------------
                mft_path = Path(path) / "$MFT"
                if not mft_path.exists():
                    r = await run_cmd_async([
                        rawcopy_exe,
                        f"/FileNamePath:{drive}\\$MFT",
                        f"/OutputPath:{extract_dir}",
                    ])
                    inner["rawcopy_mft"] = r
                    mft_path = extract_dir / "$MFT"

                if mft_path.exists():
                    r = await run_cmd_async(
                        [mftecmd_exe, "-f", str(mft_path), "--csv", str(mft_out)]
                    )
                    try:
                        r["created_tables"] = _csv_to_sqlite(mft_out)
                    except Exception as exc:
                        r["created_tables"] = []
                        r["csv_to_sqlite_error"] = str(exc)
                    inner["mftecmd_mft"] = r

                # -- $UsnJrnl ($J) -------------------------------------------
                usnjrnl_path = Path(path) / "$Extend" / "$UsnJrnl"
                if not usnjrnl_path.exists():
                    r = await run_cmd_async([
                        usnjrnl_exe,
                        f"/DevicePath:{drive}",
                        f"/OutputPath:{extract_dir}",
                    ])
                    inner["extractusnjrnl"] = r
                    usnjrnl_path = extract_dir / "$UsnJrnl"

                if usnjrnl_path.exists():
                    r = await run_cmd_async(
                        [mftecmd_exe, "-f", str(usnjrnl_path), "--csv", str(mft_out)]
                    )
                    try:
                        r["created_tables"] = _csv_to_sqlite(mft_out)
                    except Exception as exc:
                        r["created_tables"] = []
                        r["csv_to_sqlite_error"] = str(exc)
                    inner["mftecmd_usnjrnl"] = r

                return {"run_mftecmd": inner}

            subtasks["run_mftecmd"] = asyncio.create_task(_mft_work())

            # RBCmd ----------------------------------------------------------
            out = output_dir / "rbcmd"
            out.mkdir(parents=True, exist_ok=True)
            subtasks["run_rbcmd"] = asyncio.create_task(_run_tool(
                "run_rbcmd",
                [str(_get_exe("RBCmd")),
                 "-f" if Path(path).is_file() else "-d", str(Path(path / "/$Recycle.Bin")),
                 "--csv", str(out)],
                out,
            ))

            # RecentFileCacheParser ------------------------------------------
            out = output_dir / "recentfilecacheparser"
            out.mkdir(parents=True, exist_ok=True)
            subtasks["run_recentfilecacheparser"] = asyncio.create_task(_run_tool(
                "run_recentfilecacheparser",
                [str(_get_exe("RecentFileCacheParser")), "-f", path,
                 "--csv", str(out)],
                out,
            ))

            # SBECmd ---------------------------------------------------------
            sbecmd_exe = str(_get_exe("SBECmd"))
            sbecmd_base = output_dir / "sbecmd"
            sbecmd_base.mkdir(parents=True, exist_ok=True)

            if users_dir.exists():
                for user_dir in users_dir.iterdir():
                    if not user_dir.is_dir() or user_dir.name.lower() in _skip_profiles:
                        continue
                    username = user_dir.name
                    shell_dir = user_dir / "AppData/Local/Microsoft/Windows"
                    if shell_dir.exists():
                        key = f"run_sbecmd_{username}"
                        u_out = sbecmd_base / username
                        u_out.mkdir(parents=True, exist_ok=True)
                        subtasks[key] = asyncio.create_task(_run_tool(
                            key,
                            [sbecmd_exe, "-d", str(shell_dir), "--csv", str(u_out)],
                            u_out,
                        ))

            # SrumECmd -------------------------------------------------------
            out = output_dir / "srumecmd"
            out.mkdir(parents=True, exist_ok=True)
            subtasks["run_srumecmd"] = asyncio.create_task(_run_tool(
                "run_srumecmd",
                [str(_get_exe("SrumECmd")),
                 "-f", str(Path(path) / "Windows/System32/sru/SRUDB.dat"),
                 "--r", str(Path(path) / "Windows/System32/config/SOFTWARE"),
                 "--csv", str(out)],
                out,
            ))

            # SumECmd --------------------------------------------------------
            out = output_dir / "sumecmd"
            out.mkdir(parents=True, exist_ok=True)
            subtasks["run_sumecmd"] = asyncio.create_task(_run_tool(
                "run_sumecmd",
                [str(_get_exe("SumECmd")),
                 "-d", str(Path(path) / "Windows/System32/LogFiles/SUM"),
                 "--csv", str(out)],
                out,
            ))

            # Collect results ------------------------------------------------
            results: dict = {}
            for name, task in subtasks.items():
                try:
                    results.update(await task)
                except Exception as exc:
                    results[name] = {"success": False, "error": str(exc)}

            return results

        job_id = job_registry.submit("windows_full_disk", _work())
        return JobSubmitted(
            job_id=job_id,
            tool_name="windows_full_disk",
            status="pending",
            message=(
                f"All forensic tools started in parallel (RECmd expanded per user profile). "
                f"Poll get_job_status('{job_id}') to check overall completion."
            ),
        )
