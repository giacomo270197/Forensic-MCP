"""
Tests for SQLite query tools: list_tables, get_table_columns, query_table.

These tests require that at least one parsing tool has been run previously
so that database.db exists with data. Tests that depend on data are marked
with @pytest.mark.requires_db and will be skipped gracefully if the database
is not populated.
"""

import pytest
from conftest import parse_tool_result


# ───────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────


async def _db_available(mcp) -> bool:
    """Return True if list_tables succeeds (database exists with tables)."""
    try:
        result = parse_tool_result(await mcp.call_tool("list_tables", {}))
        return "tables" in result and len(result["tables"]) > 0
    except Exception:
        return False


async def _first_table(mcp) -> str | None:
    """Return the name of the first table, or None."""
    try:
        result = parse_tool_result(await mcp.call_tool("list_tables", {}))
        if result.get("tables"):
            return result["tables"][0]["table"]
    except Exception:
        pass
    return None


# ───────────────────────────────────────────────────────────────────
# list_tables
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tables_returns_structure(mcp):
    """If the DB exists, list_tables returns a dict with tables and counts."""
    try:
        result = parse_tool_result(await mcp.call_tool("list_tables", {}))
    except Exception:
        pytest.skip("Database not available — run a parsing tool first.")

    assert "tables" in result
    assert "total_tables" in result
    assert isinstance(result["tables"], list)


@pytest.mark.asyncio
async def test_list_tables_entries_have_required_keys(mcp):
    if not await _db_available(mcp):
        pytest.skip("Database not populated.")

    result = parse_tool_result(await mcp.call_tool("list_tables", {}))
    for entry in result["tables"]:
        assert "table" in entry
        assert "row_count" in entry
        assert isinstance(entry["row_count"], int)


@pytest.mark.asyncio
async def test_list_tables_total_matches_length(mcp):
    if not await _db_available(mcp):
        pytest.skip("Database not populated.")

    result = parse_tool_result(await mcp.call_tool("list_tables", {}))
    assert result["total_tables"] == len(result["tables"])


# ───────────────────────────────────────────────────────────────────
# get_table_columns
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_table_columns_valid_table(mcp):
    table = await _first_table(mcp)
    if table is None:
        pytest.skip("No tables available.")

    result = parse_tool_result(
        await mcp.call_tool("get_table_columns", {"table": table})
    )
    assert result["table"] == table
    assert "columns" in result
    assert "column_count" in result
    assert len(result["columns"]) == result["column_count"]


@pytest.mark.asyncio
async def test_get_table_columns_column_entries(mcp):
    table = await _first_table(mcp)
    if table is None:
        pytest.skip("No tables available.")

    result = parse_tool_result(
        await mcp.call_tool("get_table_columns", {"table": table})
    )
    for col in result["columns"]:
        assert "column" in col
        assert "type" in col


@pytest.mark.asyncio
async def test_get_table_columns_nonexistent_table(mcp):
    if not await _db_available(mcp):
        pytest.skip("Database not available.")

    result = parse_tool_result(
        await mcp.call_tool(
            "get_table_columns", {"table": "this_table_does_not_exist"}
        )
    )
    assert "error" in result


# ───────────────────────────────────────────────────────────────────
# query_table
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_table_select(mcp):
    table = await _first_table(mcp)
    if table is None:
        pytest.skip("No tables available.")

    result = parse_tool_result(
        await mcp.call_tool(
            "query_table", {"sql": f'SELECT * FROM "{table}" LIMIT 5'}
        )
    )
    assert result["status"] == "ok"
    assert "rows" in result
    assert "columns" in result
    assert result["row_count"] <= 5


@pytest.mark.asyncio
async def test_query_table_rejects_non_select(mcp):
    if not await _db_available(mcp):
        pytest.skip("Database not available.")

    result = parse_tool_result(
        await mcp.call_tool(
            "query_table", {"sql": "DROP TABLE IF EXISTS test_table"}
        )
    )
    assert "error" in result
    assert "SELECT" in result["error"]


@pytest.mark.asyncio
async def test_query_table_rejects_insert(mcp):
    if not await _db_available(mcp):
        pytest.skip("Database not available.")

    result = parse_tool_result(
        await mcp.call_tool(
            "query_table",
            {"sql": "INSERT INTO test VALUES (1, 'x')"},
        )
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_query_table_rejects_update(mcp):
    if not await _db_available(mcp):
        pytest.skip("Database not available.")

    result = parse_tool_result(
        await mcp.call_tool(
            "query_table",
            {"sql": "UPDATE test SET col='x'"},
        )
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_query_table_rejects_delete(mcp):
    if not await _db_available(mcp):
        pytest.skip("Database not available.")

    result = parse_tool_result(
        await mcp.call_tool(
            "query_table", {"sql": "DELETE FROM test WHERE 1=1"}
        )
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_query_table_row_limit_exceeded(mcp):
    table = await _first_table(mcp)
    if table is None:
        pytest.skip("No tables available.")

    # Check if table has > 20 rows
    count_result = parse_tool_result(
        await mcp.call_tool(
            "query_table", {"sql": f'SELECT COUNT(*) as n FROM "{table}"'}
        )
    )
    if count_result["status"] != "ok" or count_result["rows"][0]["n"] <= 20:
        pytest.skip("Table does not have enough rows to trigger limit.")

    result = parse_tool_result(
        await mcp.call_tool(
            "query_table", {"sql": f'SELECT * FROM "{table}"'}
        )
    )
    assert result["status"] == "row_limit_exceeded"
    assert "row_count" in result
    assert result["row_count"] > 20


@pytest.mark.asyncio
async def test_query_table_count_query(mcp):
    table = await _first_table(mcp)
    if table is None:
        pytest.skip("No tables available.")

    result = parse_tool_result(
        await mcp.call_tool(
            "query_table",
            {"sql": f'SELECT COUNT(*) as total FROM "{table}"'},
        )
    )
    assert result["status"] == "ok"
    assert len(result["rows"]) == 1
    assert "total" in result["rows"][0]


@pytest.mark.asyncio
async def test_query_table_invalid_sql(mcp):
    if not await _db_available(mcp):
        pytest.skip("Database not available.")

    result = parse_tool_result(
        await mcp.call_tool(
            "query_table", {"sql": "SELECT * FROM !!!invalid!!!"}
        )
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_query_table_where_clause(mcp):
    table = await _first_table(mcp)
    if table is None:
        pytest.skip("No tables available.")

    # Get a column name
    cols = parse_tool_result(
        await mcp.call_tool("get_table_columns", {"table": table})
    )
    col_name = cols["columns"][0]["column"]

    result = parse_tool_result(
        await mcp.call_tool(
            "query_table",
            {"sql": f'SELECT * FROM "{table}" WHERE "{col_name}" IS NOT NULL LIMIT 3'},
        )
    )
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_query_table_returns_sql_echo(mcp):
    table = await _first_table(mcp)
    if table is None:
        pytest.skip("No tables available.")

    sql = f'SELECT * FROM "{table}" LIMIT 1'
    result = parse_tool_result(
        await mcp.call_tool("query_table", {"sql": sql})
    )
    assert "sql" in result
