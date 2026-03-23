"""
Unit tests for mcp_tools._utils — pure helper functions.

No MCP server or external tools required.
"""

import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcp_tools._utils import (
    infer_sql_type,
    remove_prefix_timestamp,
    sanitize_column_name,
    infer_create_table_from_csv,
)


# ───────────────────────────────────────────────────────────────────
# remove_prefix_timestamp
# ───────────────────────────────────────────────────────────────────


def test_remove_valid_date_prefix():
    assert remove_prefix_timestamp("20240315_output.csv") == "_output.csv"


def test_remove_prefix_no_date():
    assert remove_prefix_timestamp("output.csv") == "output.csv"


def test_remove_prefix_invalid_date():
    # 99991301 is not a valid date
    assert remove_prefix_timestamp("99991301_data.csv") == "99991301_data.csv"


def test_remove_prefix_only_digits_valid_date():
    assert remove_prefix_timestamp("20240101rest") == "rest"


def test_remove_prefix_empty_string():
    assert remove_prefix_timestamp("") == ""


# ───────────────────────────────────────────────────────────────────
# sanitize_column_name
# ───────────────────────────────────────────────────────────────────


def test_sanitize_basic():
    assert sanitize_column_name("Column Name") == "column_name"


def test_sanitize_special_chars():
    assert sanitize_column_name("Bytes (Sent)") == "bytes_sent_"


def test_sanitize_leading_digit():
    assert sanitize_column_name("1stColumn") == "_1stcolumn"


def test_sanitize_whitespace():
    assert sanitize_column_name("  spaced  ") == "spaced"


# ───────────────────────────────────────────────────────────────────
# infer_sql_type
# ───────────────────────────────────────────────────────────────────


def test_infer_integer():
    assert infer_sql_type(["1", "2", "3"]) == "INTEGER"


def test_infer_bigint():
    big = str(2**32)
    assert infer_sql_type([big, "1"]) == "BIGINT"


def test_infer_real():
    assert infer_sql_type(["1.5", "2.3", "0.1"]) == "REAL"


def test_infer_boolean():
    assert infer_sql_type(["true", "false", "True"]) == "BOOLEAN"


def test_infer_date():
    assert infer_sql_type(["2024-03-15", "2024-01-01"]) == "DATE"


def test_infer_timestamp():
    assert infer_sql_type(["2024-03-15T14:32:01", "2024-01-01T00:00:00"]) == "TIMESTAMP"


def test_infer_text():
    assert infer_sql_type(["hello", "world"]) == "TEXT"


def test_infer_empty_values():
    assert infer_sql_type(["", "", None]) == "TEXT"


def test_infer_mixed_returns_text():
    assert infer_sql_type(["1", "hello", "2.5"]) == "TEXT"


# ───────────────────────────────────────────────────────────────────
# infer_create_table_from_csv
# ───────────────────────────────────────────────────────────────────


def test_infer_create_table(tmp_path):
    csv_file = tmp_path / "test.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Name", "Age", "Score", "Active"])
        writer.writerow(["Alice", "30", "95.5", "true"])
        writer.writerow(["Bob", "25", "88.0", "false"])

    sql = infer_create_table_from_csv(str(csv_file), table_name="people")
    assert 'CREATE TABLE "people"' in sql
    assert '"name" TEXT' in sql
    assert '"age" INTEGER' in sql
    assert '"score" REAL' in sql
    assert '"active" BOOLEAN' in sql


def test_infer_create_table_default_name(tmp_path):
    csv_file = tmp_path / "my_data.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["col1"])
        writer.writerow(["val"])

    sql = infer_create_table_from_csv(str(csv_file))
    assert '"my_data"' in sql


def test_infer_create_table_no_header(tmp_path):
    csv_file = tmp_path / "empty.csv"
    csv_file.write_text("")

    with pytest.raises(ValueError, match="no header"):
        infer_create_table_from_csv(str(csv_file))
