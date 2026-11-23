"""
test_claude_read_db.py
Unit tests for Claude's read-only database helper (.claude/tools/read_db.py)
"""

#Standard Library
import importlib.util
import json
from pathlib import Path

#Third Party Libraries
import pytest

TOOL_PATH = Path(__file__).parent.parent.parent / ".claude" / "tools" / "read_db.py"

READ_QUERIES = ["SELECT ticker FROM tickers",
                "select ticker from tickers",
                "WITH t AS (SELECT ticker FROM tickers) SELECT * FROM t",
                "-- open positions\nSELECT position_id FROM positions",
                "/* note */ SELECT 1",
                "SELECT 1;",
                "SELECT updated_at, exit_reason, executed FROM orders",
                "SELECT 'delete me' AS note",
                "SELECT 'it''s; DROP TABLE x' AS note"]

WRITE_QUERIES = ["INSERT INTO tickers (ticker) VALUES ('X')",
                 "UPDATE tickers SET is_active = 0",
                 "DELETE FROM tickers",
                 "MERGE tickers AS t USING src AS s ON 1 = 0 WHEN MATCHED THEN DELETE;",
                 "TRUNCATE TABLE tickers",
                 "EXEC sp_who",
                 "DROP TABLE tickers",
                 "SELECT 1; DROP TABLE tickers",
                 "SELECT 1; SELECT 2",
                 "SELECT * INTO tickers_copy FROM tickers",
                 "WITH t AS (SELECT 1 AS a) DELETE FROM tickers",
                 "",
                 "-- only a comment"]

DEV_ENTRY = {"server": "localhost\\SQLEXPRESS", "database": "noctis_dev", "user": "claude_reader",
             "password": "secret", "trust_server_cert": "yes"}

def load_tool():
    """Import read_db.py from .claude/tools, which isn't on the import path"""
    spec = importlib.util.spec_from_file_location("read_db", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class FakeCursor:
    """A cursor holding two columns and three rows"""
    description = [("ticker", str), ("is_active", bool)]

    def __init__(self):
        self.query = None

    def execute(self, query):
        self.query = query

    def fetchmany(self, size):
        return [("AAPL", True), ("MSFT", None), ("SPY", False)][:size]

class FakeConnection:
    """A connection that hands out one FakeCursor and records rollback and close"""

    def __init__(self):
        self.fake_cursor = FakeCursor()
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

def write_config(path, data):
    """Save a reader config file for a test"""
    path.write_text(json.dumps(data), encoding="utf-8")
    return path

@pytest.mark.parametrize("query", READ_QUERIES)
def test_is_read_only_accepts_select(query):
    """Accept a SELECT or WITH query, ignoring comments, string values and keyword-like column names"""
    read_db = load_tool()

    allowed = read_db.is_read_only(query)

    assert allowed is True

@pytest.mark.parametrize("query", WRITE_QUERIES)
def test_is_read_only_refuses_everything_else(query):
    """Refuse writes, procedure calls, SELECT INTO, a second statement and empty queries"""
    read_db = load_tool()

    allowed = read_db.is_read_only(query)

    assert allowed is False

def test_load_connection_returns_named_entry(tmp_path):
    """Return the entry for the requested database"""
    read_db = load_tool()
    path = write_config(tmp_path / "reader.local.json", {"dev": DEV_ENTRY})

    entry = read_db.load_connection(path, "dev")

    assert entry == DEV_ENTRY

def test_load_connection_missing_file_points_to_example(tmp_path):
    """Explain how to create the config file when it's missing"""
    read_db = load_tool()

    with pytest.raises(FileNotFoundError, match="reader.example.json"):
        read_db.load_connection(tmp_path / "reader.local.json", "dev")

def test_load_connection_unknown_name_lists_known_names(tmp_path):
    """Name the databases the file does have when asked for one it doesn't"""
    read_db = load_tool()
    path = write_config(tmp_path / "reader.local.json", {"dev": DEV_ENTRY})

    with pytest.raises(ValueError, match=r"Unknown database 'prod'\. Expected one of \['dev'\]"):
        read_db.load_connection(path, "prod")

def test_load_connection_missing_key_names_it(tmp_path):
    """Name every setting an entry is missing"""
    read_db = load_tool()
    entry = {key: value for key, value in DEV_ENTRY.items() if key not in ("password", "user")}
    path = write_config(tmp_path / "reader.local.json", {"dev": entry})

    with pytest.raises(ValueError, match=r"'dev' is missing \['password', 'user'\]"):
        read_db.load_connection(path, "dev")

def test_build_connection_string_uses_entry_settings():
    """Build an encrypted SQL login connection from the entry"""
    read_db = load_tool()

    text = read_db.build_connection_string(DEV_ENTRY)

    assert "SERVER={localhost\\SQLEXPRESS};" in text
    assert "DATABASE={noctis_dev};" in text
    assert "UID={claude_reader};" in text
    assert "Encrypt=yes;" in text
    assert "TrustServerCertificate=yes;" in text

def test_build_connection_string_escapes_password():
    """Keep a password with ; and } in one piece"""
    read_db = load_tool()
    entry = dict(DEV_ENTRY, password="pa}ss;word")

    text = read_db.build_connection_string(entry)

    assert "PWD={pa}}ss;word};" in text

def test_run_query_stops_at_max_rows():
    """Return at most max_rows rows and say that more exist"""
    read_db = load_tool()

    columns, rows, more = read_db.run_query(FakeConnection(), "SELECT ticker, is_active FROM tickers", max_rows=2)

    assert columns == ["ticker", "is_active"]
    assert rows == [("AAPL", True), ("MSFT", None)]
    assert more is True

def test_run_query_reports_no_more_rows():
    """Say no more rows exist when every row fits"""
    read_db = load_tool()

    _, rows, more = read_db.run_query(FakeConnection(), "SELECT ticker, is_active FROM tickers", max_rows=5)

    assert len(rows) == 3
    assert more is False

def test_format_table_lines_up_columns_and_shows_null():
    """Pad each column to its widest value and print None as NULL"""
    read_db = load_tool()

    text = read_db.format_table(["ticker", "is_active"], [("AAPL", True), ("MSFT", None)], more=False)

    assert text.splitlines() == ["ticker | is_active",
                                 "-------+----------",
                                 "AAPL   | True     ",
                                 "MSFT   | NULL     "]

def test_format_table_notes_hidden_rows():
    """Add a last line when rows were left out"""
    read_db = load_tool()

    text = read_db.format_table(["ticker"], [("AAPL",)], more=True)

    assert text.splitlines()[-1] == "(first 1 rows shown; more exist)"

def test_format_table_says_no_rows():
    """Print the header and a note when the query returned nothing"""
    read_db = load_tool()

    text = read_db.format_table(["ticker"], [], more=False)

    assert text.splitlines()[-1] == "(no rows)"

def test_main_refuses_write_without_connecting(capsys):
    """Exit with code 2 before connecting when the query isn't read-only"""
    read_db = load_tool()

    def connect(*args, **kwargs):
        raise AssertionError("main connected for a refused query")

    code = read_db.main(["DELETE FROM tickers"], connect=connect)

    assert code == 2
    assert "Refused" in capsys.readouterr().err

def test_main_prints_table_and_rolls_back(tmp_path, capsys):
    """Print the rows, then roll back and close the connection"""
    read_db = load_tool()
    path = write_config(tmp_path / "reader.local.json", {"dev": DEV_ENTRY})
    conn = FakeConnection()

    code = read_db.main(["SELECT ticker, is_active FROM tickers", "--config", str(path)],
                        connect=lambda *args, **kwargs: conn)

    assert code == 0
    assert "SPY" in capsys.readouterr().out
    assert conn.rolled_back and conn.closed

def test_main_never_prints_password(tmp_path, capsys):
    """Keep the password out of the output when the connection fails"""
    read_db = load_tool()
    path = write_config(tmp_path / "reader.local.json", {"dev": DEV_ENTRY})

    def connect(text, **kwargs):
        raise read_db.pyodbc.Error("28000", f"Login failed using {text}")

    code = read_db.main(["SELECT 1", "--config", str(path)], connect=connect)

    output = capsys.readouterr()
    assert code == 1
    assert "secret" not in output.out + output.err
