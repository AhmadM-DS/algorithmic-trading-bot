"""
test_exit_storage.py
Integration tests for storage/exits.py on noctis_test
"""

#Standard Library
from datetime import timedelta

#Third Party Libraries
import pytest

#Local Imports
from exit_samples import OPEN, add_strategy, bracket_position, strategy_id, ticker_id
from storage.exits import (get_closing_positions, get_open_buys, get_open_position, get_position_orders,
                           get_positions_by_holding_type)
from storage.orders import insert_order

def add_sell(conn, sample, number, exit_reason, status="rejected"):
    """Save a non-leg sell for a sample position"""
    position = sample["position"]
    insert_order(conn, client_order_id=f"sell-{number}", side="sell", quantity=10, order_type="market",
                 time_in_force="day", submitted_at=OPEN + timedelta(hours=1), status=status,
                 strategy_id=position["strategy_id"], ticker_id=position["ticker_id"],
                 position_id=position["position_id"], exit_reason=exit_reason)

def test_positions_by_holding_type_returns_only_that_type(bot_conn):
    """Return day positions and leave swing ones out"""
    day = bracket_position(bot_conn, add_strategy(bot_conn), number=1)
    bracket_position(bot_conn, add_strategy(bot_conn, "swinger", "swing"), number=2, holding_type="swing")

    rows = get_positions_by_holding_type(bot_conn, ["day"])

    assert [row["position_id"] for row in rows] == [day["position"]["position_id"]]
    assert rows[0]["shares_held"] == 10

def test_positions_by_holding_type_empty_list_returns_nothing(bot_conn):
    """Return nothing (and run no query) for no holding types"""

    assert get_positions_by_holding_type(bot_conn, []) == []

def test_open_position_is_none_once_closed(bot_conn):
    """Return None for a position that isn't open"""

    assert get_open_position(bot_conn, 999999) is None

def test_position_orders_are_the_buy_and_both_legs(bot_conn):
    """Return the buy, the stop and the target linked to the position"""
    sample = bracket_position(bot_conn, add_strategy(bot_conn))

    rows = get_position_orders(bot_conn, sample["position"]["position_id"])

    assert [(row["side"], row["order_type"]) for row in rows] == [("buy", "market"), ("sell", "stop"),
                                                                 ("sell", "limit")]

def test_closing_positions_need_a_bot_sell(bot_conn):
    """Find a position with a rejected signal sell, with that sell's reason"""
    sample = bracket_position(bot_conn, add_strategy(bot_conn))
    add_sell(bot_conn, sample, 1, "signal")

    rows = get_closing_positions(bot_conn)

    assert [(row["position_id"], row["last_exit_reason"]) for row in rows] == [
        (sample["position"]["position_id"], "signal")]

@pytest.mark.parametrize("exit_reason", ["manual", None])
def test_closing_positions_ignore_manual_sells_and_legs(bot_conn, exit_reason):
    """Leave out a position whose only sells are its legs or a manual sell"""
    sample = bracket_position(bot_conn, add_strategy(bot_conn))
    if exit_reason:
        add_sell(bot_conn, sample, 1, exit_reason)

    assert get_closing_positions(bot_conn) == []

def test_closing_positions_use_the_latest_reason(bot_conn):
    """Use the newest sell's reason when there were several tries"""
    sample = bracket_position(bot_conn, add_strategy(bot_conn))
    add_sell(bot_conn, sample, 1, "signal")
    add_sell(bot_conn, sample, 2, "end_of_day")

    (row,) = get_closing_positions(bot_conn)

    assert row["last_exit_reason"] == "end_of_day"

def add_buy(conn, number, strategy, status):
    insert_order(conn, client_order_id=f"buy-{number}", alpaca_order_id=f"alpaca-buy-{number}", side="buy", quantity=5,
                 order_type="market", time_in_force="day", submitted_at=OPEN, status=status, strategy_id=strategy,
                 ticker_id=ticker_id(conn, "AAPL"))

def test_open_buys_are_unfinished_day_buys_of_day_strategies(bot_conn):
    """Return a waiting day buy; leave out filled buys and manual buys"""
    momentum = add_strategy(bot_conn)
    add_buy(bot_conn, 1, momentum, "accepted")
    add_buy(bot_conn, 2, momentum, "filled")
    add_buy(bot_conn, 3, strategy_id(bot_conn, "manual"), "accepted")

    rows = get_open_buys(bot_conn, ["day"])

    assert [row["client_order_id"] for row in rows] == ["buy-1"]
