"""
test_order_schema.py
Integration tests for migration 006: bracket legs linked to their buy order
"""

#Standard Library
from datetime import date, datetime

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from storage.watchlist import get_or_create_ticker

def insert_order(conn, client_order_id, side, order_type, parent_order_id=None):
    """Insert one order as the bot and return its id"""
    ticker_id = get_or_create_ticker(conn, "AAPL", date(2026, 10, 27))
    strategy_id = conn.execute("SELECT strategy_id FROM strategies WHERE strategy = 'manual'").fetchone()[0]
    return conn.execute(
        "INSERT INTO orders (client_order_id, side, requested_quantity, order_type, time_in_force, submitted_at, "
        "[status], strategy_id, ticker_id, parent_order_id) "
        "OUTPUT INSERTED.order_id "
        "VALUES (?, ?, 10, ?, 'day', ?, 'held', ?, ?, ?)",
        (client_order_id, side, order_type, datetime(2026, 10, 27, 14, 30), strategy_id, ticker_id, parent_order_id),
    ).fetchone()[0]

def test_legs_point_to_their_buy(bot_conn):
    """Find a buy's stop and target legs through parent_order_id"""
    buy = insert_order(bot_conn, "test-AAPL-buy-1", "buy", "market")
    insert_order(bot_conn, "leg-stop-1", "sell", "stop", parent_order_id=buy)
    insert_order(bot_conn, "leg-limit-1", "sell", "limit", parent_order_id=buy)

    rows = bot_conn.execute("SELECT order_type FROM orders WHERE parent_order_id = ? ORDER BY order_type",
                            buy).fetchall()

    assert [row.order_type for row in rows] == ["limit", "stop"]

def test_buy_has_no_parent(bot_conn):
    """Leave parent_order_id empty on orders that aren't bracket legs"""
    buy = insert_order(bot_conn, "test-AAPL-buy-2", "buy", "market")

    parent = bot_conn.execute("SELECT parent_order_id FROM orders WHERE order_id = ?", buy).fetchone()[0]

    assert parent is None

def test_leg_needs_an_existing_parent(bot_conn):
    """Refuse a leg whose parent order doesn't exist"""

    with pytest.raises(pyodbc.IntegrityError, match="fk_orders_parent_order_id"):
        insert_order(bot_conn, "leg-orphan-1", "sell", "stop", parent_order_id=999999)

def test_bot_can_link_legs_after_insert(bot_conn):
    """Let the bot set parent_order_id later (orders allow UPDATE for the bot)"""
    buy = insert_order(bot_conn, "test-AAPL-buy-3", "buy", "market")
    leg = insert_order(bot_conn, "leg-stop-3", "sell", "stop")

    bot_conn.execute("UPDATE orders SET parent_order_id = ? WHERE order_id = ?", (buy, leg))

    parent = bot_conn.execute("SELECT parent_order_id FROM orders WHERE order_id = ?", leg).fetchone()[0]
    assert parent == buy

def test_parent_order_id_is_indexed(bot_conn):
    """Index parent_order_id so finding a buy's legs doesn't scan the whole table"""

    row = bot_conn.execute("SELECT 1 FROM sys.indexes WHERE name = 'ix_orders_parent_order_id' "
                           "AND object_id = OBJECT_ID('dbo.orders')").fetchone()

    assert row is not None

def test_invalid_exit_prices_ranks_after_max_order_size(bot_conn):
    """Rank invalid_exit_prices with the order-mechanics codes, after max_order_size"""

    rows = bot_conn.execute("SELECT code, [priority] FROM skip_reasons "
                            "WHERE code IN ('max_order_size', 'invalid_exit_prices')").fetchall()
    priority = {row.code: row.priority for row in rows}

    assert priority["max_order_size"] < priority["invalid_exit_prices"] == 160
