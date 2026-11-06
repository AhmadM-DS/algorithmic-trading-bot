"""
test_order_exit_reason.py
Integration tests for migration 007: why a sell order was placed
"""

#Standard Library
from datetime import date, datetime

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from storage.watchlist import get_or_create_ticker

def insert_order(conn, client_order_id, side, exit_reason=None):
    """Insert one market order as the bot and return its id"""
    ticker_id = get_or_create_ticker(conn, "AAPL", date(2026, 10, 30))
    strategy_id = conn.execute("SELECT strategy_id FROM strategies WHERE strategy = 'manual'").fetchone()[0]
    return conn.execute(
        "INSERT INTO orders (client_order_id, side, requested_quantity, order_type, time_in_force, submitted_at, "
        "[status], strategy_id, ticker_id, exit_reason) "
        "OUTPUT INSERTED.order_id "
        "VALUES (?, ?, 10, 'market', 'day', ?, 'new', ?, ?, ?)",
        (client_order_id, side, datetime(2026, 10, 30, 19, 50), strategy_id, ticker_id, exit_reason),
    ).fetchone()[0]

def check_definition(conn, name):
    """Return a CHECK constraint's definition as SQL Server stores it"""
    return conn.execute("SELECT definition FROM sys.check_constraints WHERE name = ?", name).fetchone()[0]

def test_sell_keeps_its_exit_reason(bot_conn):
    """Save why a sell was placed so A1 can copy it onto the trade"""
    sell = insert_order(bot_conn, "test-AAPL-sell-1", "sell", "end_of_day")

    reason = bot_conn.execute("SELECT exit_reason FROM orders WHERE order_id = ?", sell).fetchone()[0]

    assert reason == "end_of_day"

def test_sell_without_exit_reason_is_allowed(bot_conn):
    """Allow an empty exit_reason on a sell (rows saved before 007, or set later)"""
    sell = insert_order(bot_conn, "test-AAPL-sell-2", "sell")

    reason = bot_conn.execute("SELECT exit_reason FROM orders WHERE order_id = ?", sell).fetchone()[0]

    assert reason is None

def test_buy_cannot_have_an_exit_reason(bot_conn):
    """Refuse an exit_reason on a buy"""

    with pytest.raises(pyodbc.IntegrityError, match="ck_orders_exit_reason_sells_only"):
        insert_order(bot_conn, "test-AAPL-buy-1", "buy", "signal")

def test_unknown_exit_reason_is_refused(bot_conn):
    """Refuse a value that isn't one of the allowed exit reasons"""

    with pytest.raises(pyodbc.IntegrityError, match="ck_orders_exit_reason"):
        insert_order(bot_conn, "test-AAPL-sell-3", "sell", "felt_like_it")

def test_orders_allow_the_same_exit_reasons_as_trades_and_positions(bot_conn):
    """Keep the three exit_reason lists identical, so a reason on an order always fits its trade and position"""

    orders = check_definition(bot_conn, "ck_orders_exit_reason")

    assert orders == check_definition(bot_conn, "ck_trades_exit_reason")
    assert orders == check_definition(bot_conn, "ck_positions_exit_reason")
