"""
mcp_tools.sqlite
================
SQLite query tools that expose the forensic evidence database to the LLM.

The database is the single `database.db` file written by the CSV-to-SQLite
loader in tools.py.  These tools let the LLM explore and query that database
without ever returning unbounded result sets.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def register_tools(mcp, output_dir: Path) -> None:

    DB_PATH = output_dir / "database.db"

    def _connect() -> sqlite3.Connection:
        if not DB_PATH.exists():
            raise FileNotFoundError(
                f"Database not found at {DB_PATH}. "
                "Run a parsing tool first to populate it."
            )
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ #
    # list_tables                                                          #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def list_tables() -> dict:
        """
        List all tables in the forensic evidence database together with
        their row counts.

        Returns a dict with a ``tables`` key containing a list of objects,
        each with ``table`` (name) and ``row_count``.
        """
        conn = _connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            names = [row["name"] for row in cursor.fetchall()]
            result = []
            for name in names:
                cursor.execute(f'SELECT COUNT(*) AS n FROM "{name}"')  # noqa: S608
                count = cursor.fetchone()["n"]
                result.append({"table": name, "row_count": count})
            return {"tables": result, "total_tables": len(result)}
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # get_table_columns                                                    #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def get_table_columns(table: str) -> dict:
        """
        Return the column names and declared types for a specific table.

        Parameters
        ----------
        table:
            Name of the table to inspect (as returned by list_tables).
        """
        conn = _connect()
        try:
            cursor = conn.cursor()
            cursor.execute(f'PRAGMA table_info("{table}")')
            rows = cursor.fetchall()
            if not rows:
                return {
                    "error": f"Table '{table}' does not exist or has no columns."
                }
            columns = [
                {"column": row["name"], "type": row["type"]}
                for row in rows
            ]
            return {"table": table, "columns": columns, "column_count": len(columns)}
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # query_table                                                          #
    # ------------------------------------------------------------------ #

    MAX_ROWS = 20

    @mcp.tool()
    def query_table(sql: str) -> dict:
        """
        Execute a read-only SQL SELECT query against the forensic database.

        If the result contains more than 20 rows the actual rows are **not**
        returned; instead the response contains a message and the total
        matched row count so you can refine the query with WHERE / LIMIT.

        Parameters
        ----------
        sql:
            A SELECT statement to run.  Only SELECT queries are allowed;
            any attempt to run DDL or DML will be rejected.
        """
        normalised = sql.strip().lstrip(";").strip()
        if not normalised.upper().startswith("SELECT"):
            return {
                "error": "Only SELECT queries are permitted.",
                "sql": sql,
            }

        conn = _connect()
        try:
            cursor = conn.cursor()
            cursor.execute(normalised)
            rows = cursor.fetchall()
            total = len(rows)

            if total > MAX_ROWS:
                return {
                    "status": "row_limit_exceeded",
                    "message": (
                        f"Query matched {total} rows, which exceeds the "
                        f"maximum of {MAX_ROWS}. Refine your query using "
                        "WHERE clauses or add a LIMIT to reduce the result set."
                    ),
                    "row_count": total,
                    "sql": normalised,
                }

            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return {
                "status": "ok",
                "row_count": total,
                "columns": columns,
                "rows": [dict(row) for row in rows],
                "sql": normalised,
            }
        except sqlite3.Error as exc:
            return {"error": str(exc), "sql": normalised}
        finally:
            conn.close()
