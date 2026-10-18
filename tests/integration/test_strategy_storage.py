"""
test_strategy_storage.py
Integration tests for storage/strategies.py and storage/events.py against noctis_test
"""

#Standard Library
from datetime import date, datetime

#Local Imports
from storage.events import insert_bot_event
from storage.strategies import count_open_positions, get_active_strategies, get_strategy_rows, register_strategy
from storage.watchlist import get_or_create_ticker

def as_admin(conn, sql, params=()):
    """Run one statement as the admin (the bot has no UPDATE on strategies), then switch back"""
    conn.execute("REVERT;")
    conn.execute(sql, params)
    conn.execute("EXECUTE AS USER = 'test_bot';")

def open_position(conn, strategy_id):
    """Insert one open day position for a strategy"""
    ticker_id = get_or_create_ticker(conn, "AAPL", date(2026, 10, 19))
    conn.execute("INSERT INTO positions (time_frame, holding_type, opened_at, [status], entry_quantity, "
                 "avg_entry_price, strategy_id, ticker_id) VALUES ('15Min', 'day', ?, 'open', 10, 100, ?, ?)",
                 (datetime(2026, 10, 19, 14, 0), strategy_id, ticker_id))

def test_new_strategy_is_inactive_with_no_budget(bot_conn):
    """Register a new strategy switched off and unfunded"""
    inserted = register_strategy(bot_conn, "rsi_reversal", "15Min", "day")

    row = get_strategy_rows(bot_conn)["rsi_reversal"]

    assert inserted is True
    assert row["is_active"] is False
    assert row["budget"] == 0
    assert row["time_frame"] == "15Min" and row["default_holding_type"] == "day"

def test_registering_twice_keeps_one_row(bot_conn):
    """Return False and keep the first row when a name is registered again"""
    register_strategy(bot_conn, "rsi_reversal", "15Min", "day")

    inserted = register_strategy(bot_conn, "rsi_reversal", "30Min", "day")

    assert inserted is False
    assert get_strategy_rows(bot_conn)["rsi_reversal"]["time_frame"] == "15Min"

def test_strategy_rows_include_inactive_rows(bot_conn):
    """Return every row, including the inactive manual and unknown seed rows"""
    register_strategy(bot_conn, "rsi_reversal", "15Min", "day")

    rows = get_strategy_rows(bot_conn)

    assert {"manual", "unknown", "rsi_reversal"} <= set(rows)

def test_active_strategies_only_returns_switched_on_rows(bot_conn):
    """Return only rows the admin set to is_active = 1"""
    register_strategy(bot_conn, "rsi_reversal", "15Min", "day")
    register_strategy(bot_conn, "ema_cross", "15Min", "day")
    as_admin(bot_conn, "UPDATE strategies SET is_active = 1, budget = 5000 WHERE strategy = 'ema_cross'")

    active = get_active_strategies(bot_conn)

    assert [row["strategy"] for row in active] == ["ema_cross"]
    assert active[0]["budget"] == 5000

def test_open_positions_are_counted_per_strategy(bot_conn):
    """Count only the given strategy's open positions"""
    register_strategy(bot_conn, "rsi_reversal", "15Min", "day")
    register_strategy(bot_conn, "ema_cross", "15Min", "day")
    rows = get_strategy_rows(bot_conn)
    open_position(bot_conn, rows["rsi_reversal"]["strategy_id"])

    assert count_open_positions(bot_conn, rows["rsi_reversal"]["strategy_id"]) == 1
    assert count_open_positions(bot_conn, rows["ema_cross"]["strategy_id"]) == 0

def test_bot_event_is_saved_with_strategy(bot_conn):
    """Save a bot event with its details, strategy and a database-filled time"""
    register_strategy(bot_conn, "rsi_reversal", "15Min", "day")
    strategy_id = get_strategy_rows(bot_conn)["rsi_reversal"]["strategy_id"]

    insert_bot_event(bot_conn, "strategy_skipped", details="rsi_reversal: test", strategy_id=strategy_id)

    row = bot_conn.execute("SELECT event_type, details, strategy_id, occurred_at FROM bot_events").fetchone()
    assert row.event_type == "strategy_skipped" and row.details == "rsi_reversal: test"
    assert row.strategy_id == strategy_id
    assert row.occurred_at is not None

def test_bot_event_without_strategy_is_saved(bot_conn):
    """Save a bot event that isn't about a strategy"""
    insert_bot_event(bot_conn, "startup")

    row = bot_conn.execute("SELECT details, strategy_id FROM bot_events").fetchone()

    assert row.details is None and row.strategy_id is None
