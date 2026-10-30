"""
test_order_storage.py
Integration tests for storage/orders.py, run as the bot against noctis_test
"""

#Standard Library
from datetime import date, datetime
from decimal import Decimal

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from storage.connections import is_duplicate_error
from storage.orders import (get_stuck_orders, insert_order, save_broker_answer, save_rejection,
                            set_order_status)
from storage.watchlist import get_or_create_ticker

SAVED_AT = datetime(2026, 10, 27, 14, 30)

def new_order(conn, client_order_id="momentum-AAPL-buy-20261027T143000Z-0001", **overrides):
    """Insert a buy as place_order would, with any column overridden, and return its order_id"""
    strategy_id = conn.execute("SELECT strategy_id FROM strategies WHERE strategy = 'manual'").fetchone()[0]
    values = {"client_order_id": client_order_id, "side": "buy", "quantity": 10, "order_type": "market",
              "time_in_force": "day", "submitted_at": SAVED_AT, "status": "submitting",
              "strategy_id": strategy_id, "ticker_id": get_or_create_ticker(conn, "AAPL", date(2026, 10, 27)),
              "request_price": Decimal("5.1234")}
    values.update(overrides)
    return insert_order(conn, **values)

def order_row(conn, order_id):
    """Return one orders row"""
    return conn.execute("SELECT * FROM orders WHERE order_id = ?", order_id).fetchone()

def test_insert_saves_every_column(bot_conn):
    """Save what the bot asked for, with no Alpaca ID yet"""
    order_id = new_order(bot_conn)

    row = order_row(bot_conn, order_id)

    assert (row.client_order_id, row.side, row.requested_quantity, row.order_type, row.time_in_force) == \
           ("momentum-AAPL-buy-20261027T143000Z-0001", "buy", 10, "market", "day")
    assert (row.submitted_at, row.status, row.request_price) == (SAVED_AT, "submitting", Decimal("5.1234"))
    assert (row.alpaca_order_id, row.filled_quantity, row.filled_price, row.reject_reason) == (None, 0, None, None)
    assert (row.signal_id, row.position_id, row.parent_order_id) == (None, None, None)

def test_insert_returns_a_new_id_each_time(bot_conn):
    """Give every order its own order_id"""

    first = new_order(bot_conn, "coid-1")
    second = new_order(bot_conn, "coid-2")

    assert second != first

def test_insert_refuses_a_repeated_client_order_id(bot_conn):
    """Never save two orders with the same client_order_id"""
    new_order(bot_conn, "coid-dup")

    with pytest.raises(pyodbc.IntegrityError) as error:
        new_order(bot_conn, "coid-dup")

    assert is_duplicate_error(error.value)

def test_insert_saves_a_leg_with_its_parent_and_alpaca_id(bot_conn):
    """Save a bracket leg linked to its buy, with the IDs Alpaca made"""
    buy = new_order(bot_conn, "coid-buy")

    leg = new_order(bot_conn, "alpaca-leg-coid", side="sell", order_type="stop", status="held",
                    request_price=Decimal("5.02"), parent_order_id=buy, alpaca_order_id="alpaca-leg-id")

    row = order_row(bot_conn, leg)
    assert (row.parent_order_id, row.alpaca_order_id, row.status, row.request_price) == \
           (buy, "alpaca-leg-id", "held", Decimal("5.02"))

def test_broker_answer_updates_only_alpaca_columns(bot_conn):
    """Copy Alpaca's ID, status and fill onto the row; leave the request as it was"""
    order_id = new_order(bot_conn)

    save_broker_answer(bot_conn, order_id, "alpaca-1", "filled", 10, Decimal("5.13"))

    row = order_row(bot_conn, order_id)
    assert (row.alpaca_order_id, row.status, row.filled_quantity, row.filled_price) == \
           ("alpaca-1", "filled", 10, Decimal("5.13"))
    assert (row.requested_quantity, row.request_price, row.submitted_at) == (10, Decimal("5.1234"), SAVED_AT)

def test_broker_answer_changes_no_other_order(bot_conn):
    """Update only the order asked for"""
    order_id = new_order(bot_conn, "coid-a")
    other = new_order(bot_conn, "coid-b")

    save_broker_answer(bot_conn, order_id, "alpaca-a", "accepted", 0, None)

    assert order_row(bot_conn, other).status == "submitting"

def test_broker_answer_for_missing_order_raises(bot_conn):
    """Fail loudly instead of updating nothing"""

    with pytest.raises(LookupError, match="999999"):
        save_broker_answer(bot_conn, 999999, "alpaca-x", "accepted", 0, None)

def test_rejection_saves_status_and_reason(bot_conn):
    """Mark the order rejected with Alpaca's message"""
    order_id = new_order(bot_conn)

    save_rejection(bot_conn, order_id, "insufficient buying power")

    row = order_row(bot_conn, order_id)
    assert (row.status, row.reject_reason) == ("rejected", "insufficient buying power")

def test_rejection_cuts_a_long_reason(bot_conn):
    """Keep the first 256 characters of a long message instead of failing"""
    order_id = new_order(bot_conn)

    save_rejection(bot_conn, order_id, "x" * 300)

    assert order_row(bot_conn, order_id).reject_reason == "x" * 256

def test_set_status_changes_only_the_status(bot_conn):
    """Change the status and nothing else"""
    order_id = new_order(bot_conn)

    set_order_status(bot_conn, order_id, "unknown")

    row = order_row(bot_conn, order_id)
    assert (row.status, row.alpaca_order_id, row.reject_reason) == ("unknown", None, None)

def test_set_status_for_missing_order_raises(bot_conn):
    """Fail loudly instead of updating nothing"""

    with pytest.raises(LookupError):
        set_order_status(bot_conn, 999999, "unknown")

def test_stuck_orders_are_old_submitting_or_unknown_oldest_first(bot_conn):
    """Return only submitting / unknown orders saved before the cutoff, oldest first"""
    unknown = new_order(bot_conn, "coid-unknown", submitted_at=datetime(2026, 10, 27, 14, 0), status="unknown")
    submitting = new_order(bot_conn, "coid-submitting", submitted_at=datetime(2026, 10, 27, 14, 10))
    new_order(bot_conn, "coid-accepted", submitted_at=datetime(2026, 10, 27, 14, 5), status="accepted")
    new_order(bot_conn, "coid-rejected", submitted_at=datetime(2026, 10, 27, 14, 5), status="rejected")
    new_order(bot_conn, "coid-too-new", submitted_at=datetime(2026, 10, 27, 14, 30))

    ids = order_row(bot_conn, unknown)

    stuck = get_stuck_orders(bot_conn, before=datetime(2026, 10, 27, 14, 29))

    same = {"strategy_id": ids.strategy_id, "ticker_id": ids.ticker_id, "signal_id": None}
    assert stuck == [{"order_id": unknown, "client_order_id": "coid-unknown", "status": "unknown", **same},
                     {"order_id": submitting, "client_order_id": "coid-submitting", "status": "submitting", **same}]

def test_no_stuck_orders_returns_empty_list(bot_conn):
    """Return an empty list when nothing is stuck"""

    assert get_stuck_orders(bot_conn, before=datetime(2026, 10, 27, 14, 29)) == []
