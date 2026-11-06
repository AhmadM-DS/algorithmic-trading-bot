"""
test_fill_catch_up.py
Integration tests for fills.catch_up: missed fills, missed status changes and the retry pass (A1 decisions 2, 4)
"""

#Standard Library
from datetime import datetime
from decimal import Decimal

#Third Party Libraries
import pytest

#Local Imports
from execution.broker import BrokerOrder
from fill_samples import (NOW, CommitCounter, add_bracket, add_strategy, fill, order, positions, trades)
from fills.catch_up import catch_up, catch_up_start
from fills.handler import process_update

class FakeBroker:
    """Stands in for AlpacaBroker: returns the given activities and orders, and records what was asked"""

    def __init__(self, activities=(), orders=None):
        self.activities = list(activities)
        self.orders = orders or {}
        self.asked_since = None

    def get_fill_activities(self, since):
        self.asked_since = since
        return self.activities

    def get_order(self, alpaca_order_id):
        return self.orders.get(alpaca_order_id)

def activity(alpaca_order_id, fill_id, quantity=10, price="5.01", side="buy", cum=10, leaves=0,
             at="2026-11-02T14:31:04.000000Z", status="filled"):
    """Return a FILL activity as Alpaca's endpoint sends it"""
    return {"id": f"20261102093104000::{fill_id}", "activity_type": "FILL", "transaction_time": at, "type": "fill",
            "price": price, "qty": str(quantity), "side": side, "symbol": "AAPL", "leaves_qty": str(leaves),
            "order_id": alpaca_order_id, "cum_qty": str(cum), "order_status": status}

def broker_order(alpaca_order_id, status, order_type="stop", filled=0):
    """Return Alpaca's current version of an order as a lookup gives it"""
    return BrokerOrder(alpaca_order_id, f"coid-{alpaca_order_id}", "sell", order_type, "day", status, 10, filled,
                       None, Decimal("4.90"), None)

@pytest.fixture
def conn(bot_conn):
    return CommitCounter(bot_conn)

@pytest.fixture
def strategy_id(bot_conn):
    return add_strategy(bot_conn)

def raw_events(conn, event_type):
    return conn.execute("SELECT * FROM broker_events WHERE event_type = ? ORDER BY broker_event_id",
                        event_type).fetchall()

def test_first_catch_up_starts_at_new_york_midnight(conn):
    """Ask for today's fills from 00:00 New York (04:00 or 05:00 UTC) when nothing is saved yet"""

    start = catch_up_start(conn, datetime(2026, 11, 2, 15, 0))

    assert start == datetime(2026, 11, 2, 5, 0)

def test_later_catch_ups_start_before_the_newest_saved_event(conn, strategy_id):
    """Start 5 minutes before the newest saved event, so nothing near the edge is missed"""
    add_bracket(conn, strategy_id)
    process_update(conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), NOW)

    start = catch_up_start(conn, NOW)

    assert start == datetime(2026, 11, 2, 14, 26, 4)

def test_missed_fill_is_saved_raw_and_handled_like_a_stream_fill(conn, strategy_id):
    """Record a fill the stream never sent: raw catch_up_fill row, trade and position"""
    add_bracket(conn, strategy_id)
    broker = FakeBroker(activities=[activity("alpaca-buy-1", "exec-buy-1")])

    result = catch_up(conn, broker, NOW)

    assert (result.fills, len(raw_events(conn, "catch_up_fill"))) == (1, 1)
    assert (trades(conn)[0].alpaca_fill_id, positions(conn)[0].entry_quantity) == ("exec-buy-1", 10)

def test_missed_fill_saves_the_orders_price(conn, strategy_id):
    """Fill in orders.filled_price from the trade: an activity has no average price and the status sync skips filled orders"""
    ids = add_bracket(conn, strategy_id)

    catch_up(conn, FakeBroker(activities=[activity("alpaca-buy-1", "exec-buy-1", price="5.01")]), NOW)

    assert order(conn, ids["buy"]).filled_price == Decimal("5.01")

def test_missed_partial_fills_save_the_average_price(conn, strategy_id):
    """Average the order's trades by shares: 4 @ 5.00 and 6 @ 5.10 is 5.06, even after the stream saved the first piece"""
    ids = add_bracket(conn, strategy_id)
    process_update(conn, fill("alpaca-buy-1", 4, Decimal("5.00"), "exec-buy-1", filled=4), NOW)
    broker = FakeBroker(activities=[activity("alpaca-buy-1", "exec-buy-2", quantity=6, price="5.10")])

    catch_up(conn, broker, NOW)

    assert order(conn, ids["buy"]).filled_price == Decimal("5.06")

def test_fill_the_stream_already_saved_is_skipped(conn, strategy_id):
    """Skip an activity whose fill is already in broker_events, so nothing is saved twice"""
    add_bracket(conn, strategy_id)
    process_update(conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), NOW)
    broker = FakeBroker(activities=[activity("alpaca-buy-1", "exec-buy-1")])

    result = catch_up(conn, broker, NOW)

    assert (result.fills, raw_events(conn, "catch_up_fill"), len(trades(conn))) == (0, [], 1)

def test_missed_fills_are_handled_oldest_first(conn, strategy_id):
    """Handle the buy before the sell even if Alpaca lists them the other way"""
    ids = add_bracket(conn, strategy_id)
    broker = FakeBroker(activities=[
        activity("alpaca-stop-1", "exec-stop-1", price="4.90", side="sell", at="2026-11-02T14:45:00Z"),
        activity("alpaca-buy-1", "exec-buy-1", at="2026-11-02T14:31:04Z")])

    catch_up(conn, broker, NOW)

    assert [t.side for t in trades(conn)] == ["buy", "sell"]
    assert (positions(conn)[0].status, positions(conn)[0].exit_reason) == ("closed", "stop_loss")
    assert order(conn, ids["stop"]).status == "filled"

def test_status_changed_while_away_is_saved_and_applied(conn, strategy_id):
    """Look up open orders and save a leg canceled while the stream wasn't listening"""
    ids = add_bracket(conn, strategy_id)
    broker = FakeBroker(orders={"alpaca-limit-1": broker_order("alpaca-limit-1", "canceled", "limit")})

    result = catch_up(conn, broker, NOW)

    assert (result.status_changes, order(conn, ids["target"]).status) == (1, "canceled")
    assert raw_events(conn, "catch_up_status")[0].alpaca_order_id == "alpaca-limit-1"

def test_unchanged_orders_are_not_saved_again(conn, strategy_id):
    """Save nothing when Alpaca's status matches the row"""
    add_bracket(conn, strategy_id)
    broker = FakeBroker(orders={"alpaca-stop-1": broker_order("alpaca-stop-1", "held")})

    result = catch_up(conn, broker, NOW)

    assert (result.found_anything, raw_events(conn, "catch_up_status")) == (False, [])

def test_waiting_fill_is_handled_once_its_order_row_exists(conn, strategy_id):
    """Retry a stream fill that arrived before E1 saved its row, once the row is there"""
    early = datetime(2026, 11, 2, 14, 31, 10)
    process_update(conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), early)
    add_bracket(conn, strategy_id)

    result = catch_up(conn, FakeBroker(), NOW)

    assert (result.retried, len(trades(conn)), positions(conn)[0].strategy_id) == (1, 1, strategy_id)

def test_still_waiting_fill_is_not_counted_as_retried(conn):
    """Leave a fill that's still inside its wait for the next catch-up"""
    early = datetime(2026, 11, 2, 14, 31, 10)
    process_update(conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), early)

    result = catch_up(conn, FakeBroker(), early)

    assert (result.retried, trades(conn)) == (0, [])
