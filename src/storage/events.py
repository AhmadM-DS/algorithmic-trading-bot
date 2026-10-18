"""
events.py
Write to the bot_events table
"""

#Local Imports
from logger import db_log

def insert_bot_event(conn, event_type: str, details: str | None = None, strategy_id: int | None = None):
    """Save one bot_events row

    occurred_at is filled in by the database (UTC now). Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        event_type (str): What happened, e.g. "strategy_skipped"
        details (str | None): A readable description of the event
        strategy_id (int | None): The strategy it's about, or None if it isn't about one
    """
    conn.cursor().execute(
        "INSERT INTO bot_events (event_type, details, strategy_id) VALUES (?, ?, ?)",
        (event_type, details, strategy_id),
    )
    db_log.debug(f"bot_events saved: {event_type} (strategy_id {strategy_id})")
