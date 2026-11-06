"""
test_fill_handler.py
Integration tests for fills.handler: how each Alpaca update changes orders, trades and positions (A1 decisions 2, 5-9)
"""

#Standard Library
from datetime import datetime, timedelta
from decimal import Decimal

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from fill_samples import (FILLED_AT, NOW, CommitCounter, add_bracket, add_legs, add_sell, add_strategy, fill,
                          leg_ids, order, positions, status_event, trades)
from fills.handler import handle_update, process_update

@pytest.fixture
def strategy_id(bot_conn):
    return add_strategy(bot_conn)

def open_position(conn, strategy_id, quantity=10, price="5.00"):
    """Fill a bracket buy completely and return (order ids, position_id)"""
    ids = add_bracket(conn, strategy_id, quantity=quantity)
    handle_update(conn, fill("alpaca-buy-1", quantity, Decimal(price), "exec-buy-1", quantity=quantity), NOW)
    return ids, order(conn, ids["buy"]).position_id

def test_buy_fill_opens_a_position_for_its_strategy(bot_conn, strategy_id):
    """Open one position owned by the order's strategy, sized and priced by the fill"""
    add_bracket(bot_conn, strategy_id)

    result = handle_update(bot_conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), NOW)

    position, = positions(bot_conn)
    assert result.outcome == "handled"
    assert (position.strategy_id, position.status, position.entry_quantity, position.avg_entry_price) == \
           (strategy_id, "open", 10, Decimal("5.01"))
    assert (position.time_frame, position.holding_type, position.opened_at) == ("15Min", "day", FILLED_AT)

def test_buy_fill_saves_one_trade(bot_conn, strategy_id):
    """Save the fill as a buy trade with Alpaca's fill ID, linked to the order and position"""
    ids = add_bracket(bot_conn, strategy_id)

    handle_update(bot_conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), NOW)

    trade, = trades(bot_conn)
    assert (trade.alpaca_fill_id, trade.side, trade.quantity, trade.fill_price, trade.exit_reason) == \
           ("exec-buy-1", "buy", 10, Decimal("5.01"), None)
    assert (trade.order_id, trade.position_id, trade.filled_at) == (ids["buy"], positions(bot_conn)[0].position_id,
                                                                    FILLED_AT)

def test_buy_fill_updates_the_order_and_links_it_and_its_legs(bot_conn, strategy_id):
    """Mark the buy filled and link the buy and both legs to the new position"""
    ids = add_bracket(bot_conn, strategy_id)

    handle_update(bot_conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), NOW)

    position_id = positions(bot_conn)[0].position_id
    buy = order(bot_conn, ids["buy"])
    assert (buy.status, buy.filled_quantity, buy.filled_price) == ("filled", 10, Decimal("5.01"))
    assert [order(bot_conn, ids[key]).position_id for key in ("buy", "target", "stop")] == [position_id] * 3

def test_partial_fills_build_one_position_with_a_weighted_average(bot_conn, strategy_id):
    """Add a second partial fill to the same position: 4 @ 5.00 + 6 @ 5.10 = 10 @ 5.06"""
    add_bracket(bot_conn, strategy_id)

    handle_update(bot_conn, fill("alpaca-buy-1", 4, Decimal("5.00"), "exec-1", filled=4), NOW)
    handle_update(bot_conn, fill("alpaca-buy-1", 6, Decimal("5.10"), "exec-2", filled=10, average="5.06"), NOW)

    position, = positions(bot_conn)
    assert (position.entry_quantity, position.avg_entry_price) == (10, Decimal("5.06"))
    assert [t.quantity for t in trades(bot_conn)] == [4, 6]

def test_buy_matched_by_client_order_id_before_its_alpaca_id_is_saved(bot_conn, strategy_id):
    """Find the buy by client_order_id when E1 hasn't saved Alpaca's ID yet, and save it"""
    ids = add_bracket(bot_conn, strategy_id, legs=False)
    bot_conn.execute("UPDATE orders SET alpaca_order_id = NULL, [status] = 'submitting' WHERE order_id = ?",
                     ids["buy"])

    handle_update(bot_conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1",
                                 client_order_id="momentum-AAPL-buy-1"), NOW)

    assert (order(bot_conn, ids["buy"]).alpaca_order_id, order(bot_conn, ids["buy"]).status) == \
           ("alpaca-buy-1", "filled")

def test_leg_saved_after_the_buy_filled_copies_the_position_on_its_next_event(bot_conn, strategy_id):
    """Link a leg E1 saved after the fill when the leg's own event arrives (decision 6's race)"""
    ids = add_bracket(bot_conn, strategy_id, legs=False)
    handle_update(bot_conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), NOW)
    add_legs(bot_conn, strategy_id, ids["buy"])
    target = leg_ids(bot_conn, ids["buy"])["target"]

    handle_update(bot_conn, status_event("new", "alpaca-limit-1", order_type="limit"), NOW)

    assert order(bot_conn, target).position_id == order(bot_conn, ids["buy"]).position_id

def test_stop_fill_closes_the_position_with_its_reason_and_pnl(bot_conn, strategy_id):
    """Close the position when the stop leg sells every share: 10 x (4.90 - 5.00) = -1.00"""
    ids, position_id = open_position(bot_conn, strategy_id)

    result = handle_update(bot_conn, fill("alpaca-stop-1", 10, Decimal("4.90"), "exec-stop-1", side="sell",
                                          order_type="stop"), NOW)

    position, = positions(bot_conn)
    assert result.outcome == "handled"
    assert (position.status, position.closed_at, position.exit_reason, position.realized_pnl) == \
           ("closed", FILLED_AT, "stop_loss", Decimal("-1.0000"))
    assert (trades(bot_conn)[-1].side, trades(bot_conn)[-1].exit_reason) == ("sell", "stop_loss")

def test_target_fill_is_a_take_profit(bot_conn, strategy_id):
    """Use the target leg's saved reason, take_profit"""
    open_position(bot_conn, strategy_id)

    handle_update(bot_conn, fill("alpaca-limit-1", 10, Decimal("5.20"), "exec-target-1", side="sell",
                                 order_type="limit"), NOW)

    assert (positions(bot_conn)[0].exit_reason, positions(bot_conn)[0].realized_pnl) == \
           ("take_profit", Decimal("2.0000"))

def test_partial_sell_leaves_the_position_open(bot_conn, strategy_id):
    """Keep the position open while shares are left"""
    _, position_id = open_position(bot_conn, strategy_id)
    add_sell(bot_conn, strategy_id, position_id, exit_reason="signal")

    handle_update(bot_conn, fill("alpaca-sell-1", 4, Decimal("5.10"), "exec-sell-1", filled=4, side="sell"), NOW)

    position, = positions(bot_conn)
    assert (position.status, position.exit_reason, position.realized_pnl) == ("open", None, None)

def test_sell_from_e3_uses_the_orders_exit_reason(bot_conn, strategy_id):
    """Close with the reason E3 saved on its sell order"""
    _, position_id = open_position(bot_conn, strategy_id)
    add_sell(bot_conn, strategy_id, position_id, exit_reason="end_of_day")

    handle_update(bot_conn, fill("alpaca-sell-1", 10, Decimal("5.05"), "exec-sell-1", side="sell"), NOW)

    assert (positions(bot_conn)[0].exit_reason, positions(bot_conn)[0].realized_pnl) == \
           ("end_of_day", Decimal("0.5000"))

def test_same_fill_twice_is_saved_once(bot_conn, strategy_id):
    """Treat a fill already saved as a duplicate: no second trade, no extra shares"""
    add_bracket(bot_conn, strategy_id)
    first = fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1")
    handle_update(bot_conn, first, NOW)

    result = handle_update(bot_conn, first, NOW)

    assert result.outcome == "duplicate"
    assert (len(trades(bot_conn)), positions(bot_conn)[0].entry_quantity) == (1, 10)

def test_fill_for_an_unknown_order_waits_at_first(bot_conn):
    """Wait for E1 to save the order row instead of calling it manual right away"""
    recent = FILLED_AT + timedelta(seconds=30)

    result = handle_update(bot_conn, fill("alpaca-not-saved-yet", 10, Decimal("5.01"), "exec-1"), recent)

    assert (result.outcome, trades(bot_conn), positions(bot_conn)) == ("waiting", [], [])

def test_non_fill_event_for_an_unknown_order_changes_nothing(bot_conn):
    """Ignore a status event for an order the bot has no row for"""

    result = handle_update(bot_conn, status_event("new", "alpaca-unknown"), NOW)

    assert result.outcome == "no_order"

def test_old_unknown_fill_is_recorded_as_a_manual_trade(bot_conn):
    """Record a fill nobody claimed after the wait under the manual strategy, with its own position"""

    result = handle_update(bot_conn, fill("alpaca-dashboard-1", 3, Decimal("5.01"), "exec-manual-1",
                                          quantity=3), NOW)

    position, = positions(bot_conn)
    manual_order = bot_conn.execute("SELECT o.*, s.strategy FROM orders o JOIN strategies s "
                                    "ON s.strategy_id = o.strategy_id WHERE alpaca_order_id = ?",
                                    "alpaca-dashboard-1").fetchone()
    assert (result.outcome, manual_order.strategy, manual_order.status, manual_order.position_id) == \
           ("handled", "manual", "filled", position.position_id)
    assert (position.entry_quantity, position.holding_type, position.time_frame) == (3, "swing", "none")
    assert result.alerts == [("trades", "Manual trade recorded: buy 3 AAPL @ 5.01 (alpaca-dashboard-1)")]

def test_manual_sell_closes_the_oldest_bot_position_as_manual(bot_conn, strategy_id):
    """Take a dashboard 'Close position' from the bot's oldest open position, with exit_reason manual"""
    open_position(bot_conn, strategy_id)

    handle_update(bot_conn, fill("alpaca-dashboard-sell", 10, Decimal("5.03"), "exec-manual-sell", side="sell"),
                  NOW)

    position, = positions(bot_conn)
    assert (position.status, position.exit_reason, position.realized_pnl) == ("closed", "manual", Decimal("0.3000"))

def test_manual_sell_spanning_two_positions_is_not_recorded(bot_conn, strategy_id):
    """Alert instead of guessing when one manual sell is bigger than the position it would come from"""
    open_position(bot_conn, strategy_id, quantity=5)

    result = handle_update(bot_conn, fill("alpaca-dashboard-sell", 8, Decimal("5.03"), "exec-manual-sell",
                                          side="sell", quantity=8), NOW)

    assert result.outcome == "unresolved"
    assert [t.side for t in trades(bot_conn)] == ["buy"]
    assert any(channel == "critical" and "spans positions" in text for channel, text in result.alerts)

def test_bot_sell_without_an_exit_reason_is_not_recorded(bot_conn, strategy_id):
    """Alert instead of closing a position with no reason (a sell saved before migration 007)"""
    _, position_id = open_position(bot_conn, strategy_id)
    sell_id = add_sell(bot_conn, strategy_id, position_id)
    bot_conn.execute("UPDATE orders SET exit_reason = NULL WHERE order_id = ?", sell_id)

    result = handle_update(bot_conn, fill("alpaca-sell-1", 10, Decimal("5.05"), "exec-sell-1", side="sell"), NOW)

    assert (result.outcome, positions(bot_conn)[0].status) == ("unresolved", "open")
    assert "no exit_reason" in result.alerts[0][1]

def test_final_status_is_never_moved_back(bot_conn, strategy_id):
    """Keep a filled order filled when an older 'new' event arrives late"""
    ids, _ = open_position(bot_conn, strategy_id)

    handle_update(bot_conn, status_event("new", "alpaca-buy-1", side="buy", order_type="market"), NOW)

    buy = order(bot_conn, ids["buy"])
    assert (buy.status, buy.filled_quantity, buy.filled_price) == ("filled", 10, Decimal("5.00"))

def test_sibling_cancel_is_saved_without_an_alert(bot_conn, strategy_id):
    """Save the target leg's cancel after the stop filled, quietly"""
    ids, _ = open_position(bot_conn, strategy_id)

    result = handle_update(bot_conn, status_event("canceled", "alpaca-limit-1", order_type="limit"), NOW)

    assert (order(bot_conn, ids["target"]).status, result.alerts) == ("canceled", [])

def test_leg_expiring_on_an_open_position_alerts(bot_conn, strategy_id):
    """Alert when a stop expires while its position is still open (no stop overnight)"""
    open_position(bot_conn, strategy_id)

    result = handle_update(bot_conn, status_event("expired", "alpaca-stop-1"), NOW)

    assert result.alerts[0][0] == "critical" and "no stop" in result.alerts[0][1]

def test_late_rejection_saves_a_reason_and_alerts(bot_conn, strategy_id):
    """Mark an accepted order rejected with a reason and alert"""
    ids = add_bracket(bot_conn, strategy_id)

    result = handle_update(bot_conn, status_event("rejected", "alpaca-buy-1", side="buy", order_type="market"), NOW)

    assert (order(bot_conn, ids["buy"]).status, bool(order(bot_conn, ids["buy"]).reject_reason)) == ("rejected", True)
    assert result.alerts[0][0] == "critical"

def test_process_saves_the_raw_event_before_handling(bot_conn, strategy_id):
    """Commit the broker_events row first, then the handled rows"""
    add_bracket(bot_conn, strategy_id)
    conn = CommitCounter(bot_conn)

    process_update(conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), NOW)

    event = bot_conn.execute("SELECT * FROM broker_events WHERE execution_id = 'exec-buy-1'").fetchone()
    assert (event.event_type, event.alpaca_order_id, event.ticker, event.event_at) == \
           ("fill", "alpaca-buy-1", "AAPL", FILLED_AT)
    assert conn.commits == 2

def test_fill_saved_by_another_thread_at_the_same_time_is_a_quiet_duplicate(bot_conn, strategy_id, monkeypatch):
    """Treat losing the race on the UNIQUE fill ID as a duplicate, with no alert"""
    add_bracket(bot_conn, strategy_id)
    conn = CommitCounter(bot_conn)

    def lost_race(*args, **kwargs):
        raise pyodbc.IntegrityError("23000", "Cannot insert duplicate key row in object 'dbo.trades' "
                                             "with unique index 'uq_trades_alpaca_fill_id'. (2601)")

    monkeypatch.setattr("fills.handler.handle_update", lost_race)

    result = process_update(conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), NOW)

    assert (result.outcome, result.alerts, conn.rollbacks) == ("duplicate", [], 1)

def test_failed_handling_rolls_back_alerts_and_keeps_the_raw_event(bot_conn, strategy_id, monkeypatch):
    """Roll back a failed handling, keep the raw row and return a critical alert instead of raising"""
    add_bracket(bot_conn, strategy_id)
    conn = CommitCounter(bot_conn)

    def broken(*args, **kwargs):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr("fills.handler.handle_update", broken)

    result = process_update(conn, fill("alpaca-buy-1", 10, Decimal("5.01"), "exec-buy-1"), NOW)

    assert (result.outcome, conn.commits, conn.rollbacks) == ("failed", 1, 1)
    assert "database hiccup" in result.alerts[0][1]
    assert bot_conn.execute("SELECT COUNT(*) FROM broker_events WHERE execution_id = 'exec-buy-1'").fetchone()[0] == 1
