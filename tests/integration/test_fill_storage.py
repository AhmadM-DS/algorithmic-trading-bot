"""
test_fill_storage.py
Integration tests for storage/fills.py: the SQL behind the fill stream
"""

#Standard Library
from datetime import datetime
from decimal import Decimal

#Third Party Libraries
import pytest

#Local Imports
from fill_samples import FILLED_AT, add_bracket, add_strategy, order, ticker_id
from storage.fills import (add_to_position, close_position, get_entry_defaults, get_open_orders,
                           get_open_positions_for_ticker, get_position_totals, get_strategy_id, get_unhandled_fills,
                           insert_position, insert_trade, save_broker_event, update_order_from_broker)

@pytest.fixture
def strategy_id(bot_conn):
    return add_strategy(bot_conn)

def new_position(conn, strategy_id, quantity=10, price=Decimal("5.00"), opened_at=FILLED_AT):
    return insert_position(conn, strategy_id=strategy_id, ticker_id=ticker_id(conn), signal_id=None,
                           time_frame="15Min", holding_type="day", opened_at=opened_at, quantity=quantity,
                           price=price)

def new_trade(conn, position_id, order_id, fill_id, side, quantity, price):
    insert_trade(conn, fill_id=fill_id, side=side, quantity=quantity, filled_at=FILLED_AT, fill_price=Decimal(price),
                 time_frame="15Min", exit_reason="signal" if side == "sell" else None, position_id=position_id,
                 order_id=order_id)

def raw_fill(conn, event_type, execution_id):
    save_broker_event(conn, event_type=event_type, alpaca_order_id="alpaca-buy-1", client_order_id=None,
                      execution_id=execution_id, ticker="AAPL", event_at=FILLED_AT, raw_json="{}")

def test_update_saves_alpacas_id_status_and_fill(bot_conn, strategy_id):
    """Copy Alpaca's status and fill onto an open order"""
    buy = add_bracket(bot_conn, strategy_id, legs=False)["buy"]

    update_order_from_broker(bot_conn, buy, "alpaca-buy-1", "partially_filled", 4, Decimal("5.01"))

    row = order(bot_conn, buy)
    assert (row.status, row.filled_quantity, row.filled_price) == ("partially_filled", 4, Decimal("5.01"))

@pytest.mark.parametrize("final", ["filled", "canceled", "expired", "rejected", "replaced"])
def test_update_never_overwrites_a_final_status(bot_conn, strategy_id, final):
    """Keep a final status when an older event arrives late"""
    buy = add_bracket(bot_conn, strategy_id, legs=False)["buy"]
    bot_conn.execute("UPDATE orders SET [status] = ? WHERE order_id = ?", (final, buy))

    update_order_from_broker(bot_conn, buy, "alpaca-buy-1", "new", 0, None)

    assert order(bot_conn, buy).status == final

def test_update_never_lowers_the_filled_quantity(bot_conn, strategy_id):
    """Keep 10 filled when a stale event says 4"""
    buy = add_bracket(bot_conn, strategy_id, legs=False)["buy"]
    update_order_from_broker(bot_conn, buy, "alpaca-buy-1", "filled", 10, Decimal("5.02"))

    update_order_from_broker(bot_conn, buy, "alpaca-buy-1", "partially_filled", 4, Decimal("5.01"))

    row = order(bot_conn, buy)
    assert (row.filled_quantity, row.filled_price) == (10, Decimal("5.02"))

def test_update_without_a_price_keeps_the_saved_one(bot_conn, strategy_id):
    """Keep the average price when the update has none (a catch-up activity)"""
    buy = add_bracket(bot_conn, strategy_id, legs=False)["buy"]
    update_order_from_broker(bot_conn, buy, "alpaca-buy-1", "filled", 10, Decimal("5.02"))

    update_order_from_broker(bot_conn, buy, "alpaca-buy-1", "filled", 10, None)

    assert order(bot_conn, buy).filled_price == Decimal("5.02")

def test_add_to_position_weights_the_average_by_shares(bot_conn, strategy_id):
    """Turn 2 @ 580.10 plus 3 @ 580.15 into 5 @ 580.13"""
    position_id = new_position(bot_conn, strategy_id, quantity=2, price=Decimal("580.10"))

    add_to_position(bot_conn, position_id, 3, Decimal("580.15"))

    row = bot_conn.execute("SELECT entry_quantity, avg_entry_price FROM positions WHERE position_id = ?",
                           position_id).fetchone()
    assert (row.entry_quantity, row.avg_entry_price) == (5, Decimal("580.1300"))

def test_totals_count_sells_as_negative_shares(bot_conn, strategy_id):
    """Return 2 + 3 - 4 = 1 share held and the money in and out"""
    buy = add_bracket(bot_conn, strategy_id, legs=False)["buy"]
    position_id = new_position(bot_conn, strategy_id, quantity=5)
    new_trade(bot_conn, position_id, buy, "f1", "buy", 2, "5.00")
    new_trade(bot_conn, position_id, buy, "f2", "buy", 3, "5.10")
    new_trade(bot_conn, position_id, buy, "f3", "sell", 4, "5.20")

    totals = get_position_totals(bot_conn, position_id)

    assert totals == {"shares_held": 1, "bought": Decimal("25.30"), "sold": Decimal("20.80")}

def test_totals_of_a_position_with_no_trades_are_zero(bot_conn, strategy_id):
    """Return zeros, not None, when a position has no trades"""
    position_id = new_position(bot_conn, strategy_id)

    assert get_position_totals(bot_conn, position_id) == {"shares_held": 0, "bought": 0, "sold": 0}

def test_closing_a_closed_position_raises(bot_conn, strategy_id):
    """Refuse to close a position twice"""
    position_id = new_position(bot_conn, strategy_id)
    close_position(bot_conn, position_id, FILLED_AT, "signal", Decimal("1.00"))

    with pytest.raises(LookupError, match=str(position_id)):
        close_position(bot_conn, position_id, FILLED_AT, "signal", Decimal("1.00"))

def test_open_positions_list_manual_first_then_oldest(bot_conn, strategy_id):
    """Order a ticker's open positions the way a manual sell takes shares from them"""
    older = new_position(bot_conn, strategy_id, opened_at=datetime(2026, 11, 2, 14, 0))
    newer = new_position(bot_conn, strategy_id, opened_at=datetime(2026, 11, 2, 14, 30))
    manual = new_position(bot_conn, get_strategy_id(bot_conn, "manual"), opened_at=datetime(2026, 11, 2, 14, 45))

    found = get_open_positions_for_ticker(bot_conn, ticker_id(bot_conn))

    assert [p["position_id"] for p in found] == [manual, older, newer]

def test_unhandled_fills_are_fill_events_with_no_trade(bot_conn, strategy_id):
    """Return only fill events whose execution_id has no trades row (the quiz's LEFT JOIN)"""
    buy = add_bracket(bot_conn, strategy_id, legs=False)["buy"]
    position_id = new_position(bot_conn, strategy_id)
    raw_fill(bot_conn, "fill", "handled")
    raw_fill(bot_conn, "partial_fill", "missing-1")
    raw_fill(bot_conn, "catch_up_fill", "missing-2")
    raw_fill(bot_conn, "new", "not-a-fill")
    new_trade(bot_conn, position_id, buy, "handled", "buy", 10, "5.00")

    found = get_unhandled_fills(bot_conn)

    assert [row["event_type"] for row in found] == ["partial_fill", "catch_up_fill"]

def test_open_orders_skip_final_and_bot_only_statuses(bot_conn, strategy_id):
    """Look up only orders Alpaca knows that can still change"""
    ids = add_bracket(bot_conn, strategy_id)
    bot_conn.execute("UPDATE orders SET [status] = 'filled' WHERE order_id = ?", ids["buy"])
    bot_conn.execute("UPDATE orders SET [status] = 'unknown' WHERE order_id = ?", ids["target"])

    found = get_open_orders(bot_conn)

    assert [(row["alpaca_order_id"], row["ticker"]) for row in found] == [("alpaca-stop-1", "AAPL")]

def test_entry_defaults_come_from_the_strategy_without_a_signal(bot_conn, strategy_id):
    """Use the strategy's time frame and default holding type when there's no signal"""

    assert get_entry_defaults(bot_conn, strategy_id, None) == ("15Min", "day")

def test_entry_defaults_come_from_the_signal_when_there_is_one(bot_conn, strategy_id):
    """Use the signal's time frame and holding type over the strategy's"""
    signal_id = bot_conn.execute(
        "INSERT INTO signals (side, time_frame, holding_type, quantity, reason, generated_at, taken, [source], "
        "strategy_version, git_commit, market_data_plan, data_feed, strategy_id, ticker_id) "
        "OUTPUT INSERTED.signal_id VALUES ('buy', '1Hour', 'swing', 10, 'test', ?, 1, 'live', '1.0.0', 'abc', "
        "'delayed', 'sip', ?, ?)", (FILLED_AT, strategy_id, ticker_id(bot_conn))).fetchone()[0]

    assert get_entry_defaults(bot_conn, strategy_id, signal_id) == ("1Hour", "swing")

def test_unknown_strategy_name_raises(bot_conn):
    """Raise when a strategy name isn't registered"""

    with pytest.raises(LookupError, match="'nope'"):
        get_strategy_id(bot_conn, "nope")
