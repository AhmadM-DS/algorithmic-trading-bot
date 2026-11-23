"""
read_db.py
Claude's read-only window into a Noctis database: runs one SELECT as claude_reader and prints the rows
"""

#Standard Library
import argparse
import json
from pathlib import Path
import re
import sys

#Third Party Libraries
import pyodbc

CONFIG_PATH = Path(__file__).parent.parent / "reader.local.json"
EXAMPLE_NAME = "reader.example.json"
REQUIRED_KEYS = ("server", "database", "user", "password", "trust_server_cert")
MAX_ROWS = 200
LOGIN_TIMEOUT_SECONDS = 10

STRINGS_AND_COMMENTS = re.compile(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/", re.DOTALL)
FIRST_WORDS = ("select", "with")
WRITE_WORDS = re.compile(r"\b(insert|update|delete|merge|truncate|drop|alter|create|exec|execute|grant|revoke|deny"
                         r"|into)\b", re.IGNORECASE)

def is_read_only(query: str) -> bool:
    """Check whether a query is one SELECT (or WITH ... SELECT) statement that changes nothing

    String values and comments are ignored, so 'delete me' or -- update notes don't count as writes.

    Parameters:
        query (str): The T-SQL Claude wants to run

    Returns:
        True for a single SELECT / WITH statement with no write keyword, SELECT INTO or procedure call
    """
    text = STRINGS_AND_COMMENTS.sub(lambda match: "''" if match.group().startswith("'") else " ", query).strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    if not text or ";" in text:
        return False
    if text.split()[0].lower() not in FIRST_WORDS:
        return False
    return WRITE_WORDS.search(text) is None

def load_connection(path: Path, name: str) -> dict:
    """Read one database's connection settings from the reader config file

    Parameters:
        path (Path): The git-ignored config file, e.g. .claude/reader.local.json
        name (str): The database entry to use, e.g. "dev"

    Returns:
        The entry's settings: server, database, user, password, trust_server_cert

    Raises:
        FileNotFoundError if the file doesn't exist
        ValueError if the entry is missing or lacks a setting
    """
    if not path.exists():
        raise FileNotFoundError(f"No reader config at {path}. Copy {EXAMPLE_NAME} next to it and fill it in")
    entries = json.loads(path.read_text(encoding="utf-8"))
    if name not in entries:
        raise ValueError(f"Unknown database {name!r}. Expected one of {sorted(entries)}")
    missing = sorted(key for key in REQUIRED_KEYS if not entries[name].get(key))
    if missing:
        raise ValueError(f"Reader config entry {name!r} is missing {missing}")
    return entries[name]

def _brace(value: str) -> str:
    """Wrap an ODBC value in braces so ; and } inside it stay part of the value"""
    return "{" + value.replace("}", "}}") + "}"

def _password(entry: dict) -> str:
    """Return the entry's password"""
    return entry["password"]

def build_connection_string(entry: dict) -> str:
    """Build an encrypted SQL Server connection string for a SQL login

    Parameters:
        entry (dict): Settings from load_connection

    Returns:
        The ODBC connection string, with every value braced
    """
    return ("DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={_brace(entry['server'])};"
            f"DATABASE={_brace(entry['database'])};"
            f"UID={_brace(entry['user'])};"
            f"PWD={_brace(_password(entry))};"
            "Encrypt=yes;"
            f"TrustServerCertificate={entry['trust_server_cert']};")

def run_query(conn, query: str, max_rows: int = MAX_ROWS) -> tuple:
    """Run a query and fetch at most max_rows rows

    Parameters:
        conn (pyodbc.Connection): An open connection
        query (str): The query to run
        max_rows (int): The most rows to return

    Returns:
        (column names, rows, whether more rows exist)

    Raises:
        pyodbc.Error if the database refuses or fails the query
    """
    cursor = conn.cursor()
    cursor.execute(query)
    if cursor.description is None:
        return [], [], False
    columns = [column[0] for column in cursor.description]
    rows = [tuple(row) for row in cursor.fetchmany(max_rows + 1)]
    return columns, rows[:max_rows], len(rows) > max_rows

def format_table(columns: list, rows: list, more: bool) -> str:
    """Lay rows out as a plain-text table

    Parameters:
        columns (list): Column names
        rows (list): Row tuples; None prints as NULL
        more (bool): Whether rows were left out

    Returns:
        The table as text, ending with a note when there are no rows or rows were left out
    """
    cells = [["NULL" if value is None else str(value) for value in row] for row in rows]
    widths = [max([len(name)] + [len(row[index]) for row in cells]) for index, name in enumerate(columns)]
    lines = [" | ".join(name.ljust(width) for name, width in zip(columns, widths)),
             "-+-".join("-" * width for width in widths)]
    lines += [" | ".join(value.ljust(width) for value, width in zip(row, widths)) for row in cells]
    if not rows:
        lines.append("(no rows)")
    elif more:
        lines.append(f"(first {len(rows)} rows shown; more exist)")
    return "\n".join(lines)

def _scrub(error: Exception, entry: dict) -> str:
    """Return the error text with the password removed"""
    text = str(error)
    for secret in (_password(entry), _brace(_password(entry))):
        text = text.replace(secret, "***")
    return text

def main(argv: list, connect=pyodbc.connect) -> int:
    """Run one read-only query from the command line and print the rows

    Parameters:
        argv (list): Command-line arguments: the query, then optional --db, --max-rows, --config
        connect (callable): Opens the connection; tests pass a fake

    Returns:
        0 on success, 1 if the config, connection or query fails, 2 if the query isn't read-only
    """
    parser = argparse.ArgumentParser(description="Run one read-only query as claude_reader")
    parser.add_argument("query")
    parser.add_argument("--db", default="dev")
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args(argv)

    if not is_read_only(args.query):
        print("Refused: only one SELECT (or WITH ... SELECT) statement is allowed", file=sys.stderr)
        return 2
    try:
        entry = load_connection(args.config, args.db)
    except (FileNotFoundError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    try:
        conn = connect(build_connection_string(entry), autocommit=False, timeout=LOGIN_TIMEOUT_SECONDS)
    except pyodbc.Error as error:
        print(f"Couldn't connect to {args.db} as {entry['user']}: {_scrub(error, entry)}", file=sys.stderr)
        return 1
    try:
        columns, rows, more = run_query(conn, args.query, args.max_rows)
    except pyodbc.Error as error:
        print(f"Query failed: {_scrub(error, entry)}", file=sys.stderr)
        return 1
    finally:
        conn.rollback()
        conn.close()
    print(format_table(columns, rows, more))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
