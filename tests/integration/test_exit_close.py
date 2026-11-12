"""
test_exit_close.py
Integration tests for exits.close_position: a FakeExitBroker stands in for Alpaca, rows go to noctis_test
"""

#Standard Library
from decimal import Decimal

#Third Party Libraries
import pytest

#Local Imports
from execution.broker import OrderRejected
from exits import ExitWatch, close_position
from exit_samples import (MIDDAY, CommitCounter, FakeExitBroker, add_strategy, alpaca_unavailable,
                          bracket_position, leg, order_rows, sell_rows)

@pytest.fixture
def conn(bot_conn):
    """The bot connection, with commits counted instead of made"""
    return CommitCounter(bot_conn)

@pytest.fixture
def alerts(monkeypatch):
    """Capture Discord critical alerts instead of sending them"""
    sent = []
    monkeypatch.setattr("exits.close.send_critical", sent.append)
    monkeypatch.setattr("execution.orders.send_critical", sent.append)
    return sent

def close(conn, broker, sample, exit_reason="signal", sleeps=None, **options):
    """Call close_position at midday with no real waiting"""
    return close_position(sample["position"], exit_reason, conn, broker, now=MIDDAY,
                          sleep=(sleeps if sleeps is not None else []).append, **options)

def test_close_cancels_both_legs_then_sells_every_share(conn, alerts):
    """Cancel the stop and target, then sell all 10 shares with the exit reason and position on the sell"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})

    result = close(conn, broker, sample)

    assert (result.status, result.quantity) == ("sent", 10)
    assert ("cancel", "stop-1") in broker.calls and ("cancel", "target-1") in broker.calls
    assert broker.sells() == [("AAPL", 10)]
    (sell,) = sell_rows(conn, sample["position"]["position_id"])
    assert (sell.exit_reason, sell.requested_quantity, sell.time_in_force) == ("signal", 10, "day")

def test_close_saves_the_cancelled_legs(conn, alerts):
    """Save each leg's canceled status, so a restart sees the close was started"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})

    close(conn, broker, sample)

    legs = [row for row in order_rows(conn, sample["position"]["position_id"]) if row.parent_order_id is not None]
    assert {row.status for row in legs} == {"canceled"}

def test_close_cancels_before_selling(conn, alerts):
    """Send the sell only after both legs were cancelled, since they reserve the shares"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})

    close(conn, broker, sample)

    kinds = [call[0] for call in broker.calls]
    assert kinds.index("sell") > max(i for i, kind in enumerate(kinds) if kind == "cancel")

def test_stop_partly_filled_during_cancel_sells_only_the_rest(conn, alerts):
    """Sell 6 when the stop sold 4 before its cancel landed, even though the database still says 10"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 6},
                            polls={"stop-1": [leg(sample, "stop", "canceled", filled=4)]})

    result = close(conn, broker, sample)

    assert (result.status, result.quantity) == ("sent", 6)
    assert broker.sells() == [("AAPL", 6)]

def test_stop_filled_during_cancel_sells_nothing(conn, alerts):
    """Send no sell when the stop sold everything while the bot was cancelling it"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={},
                            polls={"stop-1": [leg(sample, "stop", "filled", filled=10)]})

    result = close(conn, broker, sample)

    assert result.status == "nothing_to_sell"
    assert broker.sells() == []

def test_refused_cancel_reads_the_final_status(conn, alerts):
    """Treat "not cancelable" as the race already over and sell by the leg's final fill"""
    sample = bracket_position(conn, add_strategy(conn))
    orders = [o if o.alpaca_order_id != "target-1" else leg(sample, "target", "filled", filled=10)
              for o in sample["orders"]]
    broker = FakeExitBroker(orders, positions={})

    result = close(conn, broker, sample)

    assert result.status == "nothing_to_sell"

def test_slow_cancel_waits_then_sells(conn, alerts):
    """Read the stop every second while it's pending_cancel and sell once it's canceled"""
    sample = bracket_position(conn, add_strategy(conn))
    pending = leg(sample, "stop", "pending_cancel")
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10},
                            polls={"stop-1": [pending, pending, leg(sample, "stop", "canceled")]})
    sleeps = []

    result = close(conn, broker, sample, sleeps=sleeps)

    assert result.status == "sent"
    assert sleeps == [1, 1]

def test_cancel_not_final_after_the_wait_sells_nothing(conn, alerts):
    """Send no sell while a leg is still pending_cancel after the whole wait"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10},
                            polls={"stop-1": [leg(sample, "stop", "pending_cancel")]})
    sleeps = []

    result = close(conn, broker, sample, sleeps=sleeps, wait_seconds=10)

    assert result.status == "cancel_pending"
    assert broker.sells() == []
    assert len(sleeps) == 10

def test_two_strategies_in_one_ticker_each_sell_their_own_shares(conn, alerts):
    """Sell 20 for B (its stop sold 30, not booked yet) and 50 for A, whichever closes first"""
    first = bracket_position(conn, add_strategy(conn, "alpha"), shares=50, number=1)
    second = bracket_position(conn, add_strategy(conn, "beta"), shares=50, number=2)
    broker = FakeExitBroker(first["orders"] + second["orders"],
                            polls={"stop-2": [leg(second, "stop", "canceled", filled=30)]})
    shares = {"AAPL": 70}

    b = close(conn, broker, second, shares=shares)
    a = close(conn, broker, first, shares=shares)

    assert (b.quantity, a.quantity) == (20, 50)
    assert shares == {"AAPL": 0}

def test_alpaca_holding_less_caps_the_sell(conn, alerts):
    """Sell no more than Alpaca holds, so a stale count can never open a short"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 7})

    result = close(conn, broker, sample)

    assert result.quantity == 7

def test_alpaca_short_sells_nothing_and_alerts(conn, alerts):
    """Send no sell and a critical alert when Alpaca shows a negative share count"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": -5})

    result = close(conn, broker, sample)

    assert result.status == "short"
    assert broker.sells() == []
    assert "short" in alerts[0]

def test_sell_already_out_does_nothing(conn, alerts):
    """Leave the position alone while an earlier sell for it is still at Alpaca"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})
    close(conn, broker, sample)
    broker.calls.clear()

    result = close(conn, broker, sample)

    assert result.status == "order_pending"
    assert broker.calls == []

def test_alpaca_down_during_cancel_sells_nothing(conn, alerts):
    """Send no sell when the cancel gets no answer"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10}, cancel_error=alpaca_unavailable())

    result = close(conn, broker, sample)

    assert result.status == "broker_unavailable"
    assert broker.sells() == []

def test_no_share_counts_sells_nothing(conn, alerts):
    """Never sell blind: no sell when Alpaca's positions can't be read"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions_error=alpaca_unavailable())

    result = close(conn, broker, sample)

    assert result.status == "broker_unavailable"
    assert broker.sells() == []

def test_rejected_sell_keeps_the_share_count(conn, alerts):
    """Leave the running count alone when Alpaca rejects the sell, since no shares left"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], sell_error=OrderRejected("asset AAPL is halted"))
    shares = {"AAPL": 10}

    result = close(conn, broker, sample, shares=shares)

    assert (result.status, result.detail) == ("rejected", "asset AAPL is halted")
    assert shares == {"AAPL": 10}

def test_price_given_is_saved_as_request_price(conn, alerts):
    """Save the latest price on the sell, or the entry price when none is given"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})

    close(conn, broker, sample, price=Decimal("5.37"))

    (sell,) = sell_rows(conn, sample["position"]["position_id"])
    assert sell.request_price == Decimal("5.37")

def test_close_starts_the_watch_clock(conn, alerts):
    """Record the position, its reason and the time in the watch"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})
    watch = ExitWatch()

    close(conn, broker, sample, watch=watch)

    assert watch.closing[sample["position"]["position_id"]].since == MIDDAY
    assert watch.reason(sample["position"]["position_id"]) == "signal"
