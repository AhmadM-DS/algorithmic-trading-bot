"""
test_exit_sweep.py
Integration tests for exits.run_exits: which positions and buys the sweep closes, when, and its alerts
"""

#Standard Library
from datetime import date, datetime, timedelta, timezone

#Third Party Libraries
import pandas as pd
import pytest

#Local Imports
from execution.broker import BrokerOrder, OrderRejected
from exits import ExitWatch, close_position, run_exits
from exit_samples import (CALENDAR, MIDDAY, OPEN, CommitCounter, FakeExitBroker, add_strategy, alpaca_unavailable,
                          bracket_position, sell_rows, strategy_id, ticker_id)
from storage.orders import insert_order

CLOSE_START = datetime(2026, 11, 9, 20, 50)

@pytest.fixture
def conn(bot_conn):
    """The bot connection, with commits counted instead of made"""
    return CommitCounter(bot_conn)

@pytest.fixture
def alerts(monkeypatch):
    """Capture Discord critical alerts instead of sending them"""
    sent = []
    for module in ("exits.close", "exits.sweep", "execution.orders"):
        monkeypatch.setattr(f"{module}.send_critical", sent.append)
    return sent

def sweep(conn, broker, at, watch=None, calendar=CALENDAR):
    """Run one sweep at a naive UTC time with no real waiting"""
    return run_exits(conn, broker, calendar, at.replace(tzinfo=timezone.utc), watch or ExitWatch(), sleep=[].append)

def test_closed_market_does_nothing(conn, alerts):
    """Leave everything alone outside regular hours"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})

    report = sweep(conn, broker, datetime(2026, 11, 9, 21, 5))

    assert report.status == "market_closed"
    assert broker.calls == []

def test_day_position_stays_open_before_the_close_time(conn, alerts):
    """Leave a day position alone at 15:49 New York"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})

    report = sweep(conn, broker, CLOSE_START - timedelta(minutes=1))

    assert report.results == ()
    assert broker.sells() == []

def test_day_position_closes_at_ten_minutes_before_the_close(conn, alerts):
    """Sell a day position at 15:50 New York with exit_reason end_of_day"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})

    report = sweep(conn, broker, CLOSE_START)

    assert [r.status for r in report.results] == ["sent"]
    (sell,) = sell_rows(conn, sample["position"]["position_id"])
    assert sell.exit_reason == "end_of_day"

def test_early_close_day_closes_ten_minutes_before_its_own_close(conn, alerts):
    """Sell at 12:50 New York on a half day that closes at 13:00"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})
    half_day = {date(2026, 11, 9): {"open": pd.Timestamp("2026-11-09 14:30", tz="UTC"),
                                    "close": pd.Timestamp("2026-11-09 18:00", tz="UTC")}}

    report = sweep(conn, broker, datetime(2026, 11, 9, 17, 50), calendar=half_day)

    assert broker.sells() == [("AAPL", 10)]

def test_swing_position_is_never_closed_at_the_end_of_the_day(conn, alerts):
    """Leave a swing position open through the end-of-day sweep"""
    sample = bracket_position(conn, add_strategy(conn, "swinger", "swing"), holding_type="swing")
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})

    sweep(conn, broker, CLOSE_START)

    assert broker.sells() == []

def test_day_position_closes_even_when_its_strategy_is_off(conn, alerts):
    """Close it anyway: off, halts and the kill switch only block buys"""
    momentum = add_strategy(conn)
    sample = bracket_position(conn, momentum)
    conn.execute("REVERT;")
    conn.execute("UPDATE strategies SET mode = 'off' WHERE strategy_id = ?", momentum)
    conn.execute("EXECUTE AS USER = 'test_bot';")
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})

    sweep(conn, broker, CLOSE_START)

    assert broker.sells() == [("AAPL", 10)]

def test_two_positions_in_one_ticker_share_alpacas_count(conn, alerts):
    """Read Alpaca's positions once and never sell more than it holds across both closes"""
    first = bracket_position(conn, add_strategy(conn, "alpha"), shares=50, number=1)
    second = bracket_position(conn, add_strategy(conn, "beta"), shares=50, number=2)
    broker = FakeExitBroker(first["orders"] + second["orders"], positions={"AAPL": 70})

    sweep(conn, broker, CLOSE_START)

    assert broker.sells() == [("AAPL", 50), ("AAPL", 20)]
    assert broker.calls.count(("positions",)) == 1

def test_leftover_from_an_earlier_day_closes_at_the_open_with_one_alert(conn, alerts):
    """Close a day position still open from Friday at Monday's first sweep, alerting once"""
    sample = bracket_position(conn, add_strategy(conn), opened_at=datetime(2026, 11, 6, 15, 0))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10})
    watch = ExitWatch()

    sweep(conn, broker, OPEN + timedelta(minutes=1), watch)
    sweep(conn, broker, OPEN + timedelta(minutes=2), watch)

    assert broker.sells() == [("AAPL", 10)]
    assert len([a for a in alerts if "still open at today's open" in a]) == 1
    (sell,) = sell_rows(conn, sample["position"]["position_id"])
    assert sell.exit_reason == "end_of_day"

def test_waiting_day_buy_is_cancelled_at_the_close(conn, alerts):
    """Cancel a day buy that hasn't filled yet, so it can't open a position after the sweep"""
    momentum = add_strategy(conn)
    insert_order(conn, client_order_id="late-buy", alpaca_order_id="alpaca-late-buy", side="buy", quantity=5,
                 order_type="market", time_in_force="day", submitted_at=CLOSE_START - timedelta(minutes=5),
                 status="accepted", strategy_id=momentum, ticker_id=ticker_id(conn, "HALT"))
    broker = FakeExitBroker([BrokerOrder("alpaca-late-buy", "late-buy", "buy", "market", "day", "accepted", 5, 0,
                                         None, None, None)])

    report = sweep(conn, broker, CLOSE_START)

    assert report.cancelled_buys == ("late-buy",)

def test_manual_buy_is_not_cancelled_at_the_close(conn, alerts):
    """Leave a buy placed by hand in the Alpaca app alone"""
    insert_order(conn, client_order_id="my-buy", alpaca_order_id="alpaca-my-buy", side="buy", quantity=5,
                 order_type="market", time_in_force="day", submitted_at=CLOSE_START, status="accepted",
                 strategy_id=strategy_id(conn, "manual"), ticker_id=ticker_id(conn, "MINE"))
    broker = FakeExitBroker()

    report = sweep(conn, broker, CLOSE_START)

    assert report.cancelled_buys == ()

def test_rejected_signal_sell_is_retried_next_cycle_with_its_reason(conn, alerts):
    """Try a failed signal close again at the next sweep, mid-day, still as a signal sell"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions={"AAPL": 10}, sell_error=OrderRejected("halted"))
    close_position(sample["position"], "signal", conn, broker, now=MIDDAY, sleep=[].append)
    broker.sell_error = None

    report = sweep(conn, broker, MIDDAY + timedelta(minutes=1), ExitWatch())

    assert [r.status for r in report.results] == ["sent"]
    assert [row.exit_reason for row in sell_rows(conn, sample["position"]["position_id"])] == ["signal", "signal"]

def test_stuck_close_alerts_once_after_three_minutes(conn, alerts):
    """Send one critical alert when the sell still can't go out three minutes after the close started"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions_error=alpaca_unavailable())
    watch = ExitWatch()

    for minute in range(6):
        sweep(conn, broker, CLOSE_START + timedelta(minutes=minute), watch)

    stuck = [a for a in alerts if "still open 3 minutes" in a]
    assert len(stuck) == 1

def test_no_alert_before_three_minutes(conn, alerts):
    """Stay quiet while a close has been failing for less than three minutes"""
    sample = bracket_position(conn, add_strategy(conn))
    broker = FakeExitBroker(sample["orders"], positions_error=alpaca_unavailable())
    watch = ExitWatch()

    for minute in range(3):
        sweep(conn, broker, CLOSE_START + timedelta(minutes=minute), watch)

    assert alerts == []

def test_watch_forgets_a_position_once_it_closes(conn, alerts):
    """Drop a closed position from the watch on the next sweep"""
    watch = ExitWatch()
    watch.start(999999, "signal", MIDDAY)

    sweep(conn, FakeExitBroker(), MIDDAY, watch)

    assert 999999 not in watch.closing
