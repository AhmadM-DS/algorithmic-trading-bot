"""
test_append_only.py
Integration tests for AUD-8: the bot can add rows to the audit tables but never change or delete them
"""

#Standard Library
from datetime import date, datetime

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from storage.watchlist import get_or_create_ticker

FILLED_AT = datetime(2026, 10, 30, 17, 42, 20)

def insert_trade(conn):
    """Insert a buy fill with the order and position it needs"""
    ticker_id = get_or_create_ticker(conn, "AAPL", date(2026, 10, 30))
    strategy_id = conn.execute("SELECT strategy_id FROM strategies WHERE strategy = 'manual'").fetchone()[0]
    order_id = conn.execute(
        "INSERT INTO orders (client_order_id, side, requested_quantity, order_type, time_in_force, submitted_at, "
        "[status], strategy_id, ticker_id) OUTPUT INSERTED.order_id "
        "VALUES ('test-AAPL-buy-1', 'buy', 1, 'market', 'day', ?, 'filled', ?, ?)",
        (FILLED_AT, strategy_id, ticker_id),
    ).fetchone()[0]
    position_id = conn.execute(
        "INSERT INTO positions (time_frame, holding_type, opened_at, [status], entry_quantity, avg_entry_price, "
        "strategy_id, ticker_id) OUTPUT INSERTED.position_id "
        "VALUES ('none', 'swing', ?, 'open', 1, 755.22, ?, ?)",
        (FILLED_AT, strategy_id, ticker_id),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO trades (alpaca_fill_id, side, quantity, filled_at, fill_price, time_frame, position_id, order_id) "
        "VALUES ('7f050d7a-f9cc-409b-b8e4-09a751a8ac45', 'buy', 1, ?, 755.22, 'none', ?, ?)",
        (FILLED_AT, position_id, order_id),
    )

def insert_broker_event(conn):
    conn.execute("INSERT INTO broker_events (event_type, raw_json) VALUES ('fill', '{}')")

def insert_account_activity(conn):
    conn.execute("INSERT INTO account_activities (alpaca_activity_id, activity_type, activity_at, raw_json) "
                 "VALUES ('20261030134220960::7f050d7a', 'FILL', ?, '{}')", FILLED_AT)

# table: (insert one row, a column to "change")
APPEND_ONLY = {
    "trades": (insert_trade, "quantity"),
    "broker_events": (insert_broker_event, "event_type"),
    "account_activities": (insert_account_activity, "activity_type"),
}

@pytest.mark.parametrize("table", APPEND_ONLY)
def test_bot_can_insert(bot_conn, table):
    """Let the bot add rows"""
    insert, _ = APPEND_ONLY[table]
    before = bot_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    insert(bot_conn)

    assert bot_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == before + 1

@pytest.mark.parametrize("table", APPEND_ONLY)
def test_bot_cannot_update(bot_conn, table):
    """Refuse any change to a saved row; corrections are new rows"""
    insert, column = APPEND_ONLY[table]
    insert(bot_conn)

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute(f"UPDATE {table} SET {column} = {column}")

@pytest.mark.parametrize("table", APPEND_ONLY)
def test_bot_cannot_delete(bot_conn, table):
    """Refuse deleting a saved row"""
    insert, _ = APPEND_ONLY[table]
    insert(bot_conn)

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute(f"DELETE FROM {table}")
