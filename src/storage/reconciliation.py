"""
reconciliation.py
Save and read share mismatches between Alpaca and the database as bot_events rows
"""

#Standard Library
import json

#Local Imports
from storage.events import insert_bot_event

MISMATCH = "reconciliation_mismatch"
RESOLVED = "reconciliation_resolved"

def insert_reconciliation_event(conn, event_type: str, ticker: str, alpaca: int, database: int):
    """Save one mismatch or resolved row with its counts as JSON, e.g. {"ticker": "ABC", "alpaca": 70, "database": 100}

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        event_type (str): MISMATCH or RESOLVED
        ticker (str): The ticker
        alpaca (int): Alpaca's share count
        database (int): The database's share count

    Raises:
        ValueError if event_type isn't MISMATCH or RESOLVED
    """
    if event_type not in (MISMATCH, RESOLVED):
        raise ValueError(f"Unknown reconciliation event {event_type!r}. Expected {MISMATCH!r} or {RESOLVED!r}")
    details = json.dumps({"ticker": ticker, "alpaca": alpaca, "database": database})
    insert_bot_event(conn, event_type, details)

def get_open_mismatches(conn) -> dict:
    """Return every ticker whose newest reconciliation row is a mismatch: recorded and not resolved yet

    Parameters:
        conn (Connection): An open database connection

    Returns:
        {ticker: {"occurred_at" (naive UTC), "alpaca", "database"}} with the counts saved when it was recorded
    """
    rows = conn.cursor().execute(
        "WITH saved AS ("
        "    SELECT bot_event_id, event_type, occurred_at, JSON_VALUE(details, '$.ticker') AS ticker, "
        "           CAST(JSON_VALUE(details, '$.alpaca') AS INT) AS alpaca, "
        "           CAST(JSON_VALUE(details, '$.database') AS INT) AS database_shares "
        "    FROM bot_events WHERE event_type IN (?, ?)"
        "), ranked AS ("
        "    SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY occurred_at DESC, bot_event_id DESC) AS newest "
        "    FROM saved"
        ") "
        "SELECT ticker, occurred_at, alpaca, database_shares FROM ranked WHERE newest = 1 AND event_type = ?",
        (MISMATCH, RESOLVED, MISMATCH),
    ).fetchall()
    return {row.ticker: {"occurred_at": row.occurred_at, "alpaca": row.alpaca, "database": row.database_shares}
            for row in rows}
