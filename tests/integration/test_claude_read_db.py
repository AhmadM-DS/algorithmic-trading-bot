"""
test_claude_read_db.py
Integration tests for Claude's read-only database helper, run as the test reader user on noctis_test
"""

#Standard Library
import importlib.util
from pathlib import Path

#Third Party Libraries
import pyodbc
import pytest

TOOL_PATH = Path(__file__).parent.parent.parent / ".claude" / "tools" / "read_db.py"

def load_tool():
    """Import read_db.py from .claude/tools, which isn't on the import path"""
    spec = importlib.util.spec_from_file_location("read_db", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_run_query_reads_allowed_columns(reader_conn):
    """Read an approved table as the reader and stop at max_rows"""
    read_db = load_tool()

    columns, rows, more = read_db.run_query(reader_conn, "SELECT code FROM skip_reasons ORDER BY skip_reason_id",
                                            max_rows=3)

    assert columns == ["code"]
    assert len(rows) == 3
    assert more is True

def test_run_query_refused_on_hidden_column(reader_conn):
    """Let the database refuse a money column the reader can't see"""
    read_db = load_tool()

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        read_db.run_query(reader_conn, "SELECT budget FROM strategies", max_rows=3)
