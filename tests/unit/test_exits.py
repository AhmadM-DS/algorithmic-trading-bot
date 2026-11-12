"""
test_exits.py
Unit tests for the pure parts of exits: share math, close times, the watch, E3's settings and a down database
"""

#Standard Library
from datetime import date, datetime, timedelta, timezone

#Third Party Libraries
import pandas as pd
import pyodbc

#Local Imports
from config.constants import (CANCEL_WAIT_SECONDS, CLOSING_ALERT_MINUTES, ENABLED_HOLDING_TYPES,
                              END_OF_DAY_CLOSE_MINUTES, LAST_BUY_MINUTES_BEFORE_CLOSE)
from execution.broker import BrokerOrder
from exits import ExitWatch, close_time, remaining_shares, run_exits

CLOSE = datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 9, 20, 50)
CALENDAR = {date(2026, 11, 9): {"open": pd.Timestamp("2026-11-09 14:30", tz="UTC"),
                                "close": pd.Timestamp("2026-11-09 21:00", tz="UTC")}}

def order(alpaca_order_id, side, filled):
    """Return one saved order row as get_position_orders gives it"""
    return {"alpaca_order_id": alpaca_order_id, "side": side, "filled_quantity": filled}

def answer(alpaca_order_id, side, filled):
    """Return Alpaca's answer for one order"""
    return BrokerOrder(alpaca_order_id, "x", side, "stop", "day", "canceled", 10, filled, None, None, None)

class DownConnection:
    """Stands in for a connection to a database that doesn't answer"""

    def cursor(self):
        raise pyodbc.OperationalError("08001", "Login timeout expired")

def test_remaining_shares_is_buys_minus_sells():
    """Count 10 bought minus 4 sold by the stop as 6 left"""
    orders = [order("buy", "buy", 10), order("stop", "sell", 4), order("target", "sell", 0)]

    assert remaining_shares(orders, {}) == 6

def test_remaining_shares_prefers_alpacas_answer():
    """Use Alpaca's filled count over the saved one, which the fill stream may not have updated yet"""
    orders = [order("buy", "buy", 10), order("stop", "sell", 0)]

    assert remaining_shares(orders, {"stop": answer("stop", "sell", 3)}) == 7

def test_close_time_is_minutes_before_that_days_close():
    """Start the day close 10 minutes before the close"""

    assert close_time(CLOSE, "day") == CLOSE - timedelta(minutes=END_OF_DAY_CLOSE_MINUTES["day"])

def test_close_time_is_none_for_swing():
    """Give swing positions no end-of-day close"""

    assert close_time(CLOSE, "swing") is None

def test_watch_keeps_the_first_reason_and_time():
    """Keep the first start of a close when it's started again"""
    watch = ExitWatch()

    watch.start(1, "signal", NOW)
    watch.start(1, "end_of_day", NOW + timedelta(minutes=1))

    assert (watch.reason(1), watch.closing[1].since) == ("signal", NOW)

def test_watch_reports_stuck_once():
    """Answer True only on the first check past the limit"""
    watch = ExitWatch()
    watch.start(1, "signal", NOW)

    checks = [watch.stuck(1, NOW + timedelta(minutes=minute), 3) for minute in range(6)]

    assert checks == [False, False, False, True, False, False]

def test_watch_first_time_is_true_once():
    """Let each alert key through once"""
    watch = ExitWatch()

    assert [watch.first_time(("leftover", 1)), watch.first_time(("leftover", 1))] == [True, False]

def test_every_enabled_holding_type_closing_at_the_end_of_the_day_closes_after_the_last_buy():
    """Keep each close time inside the last buy margin, so no buy can land after the sweep"""

    assert all(0 < END_OF_DAY_CLOSE_MINUTES[ht] < LAST_BUY_MINUTES_BEFORE_CLOSE[ht]
               for ht in ENABLED_HOLDING_TYPES if ht in END_OF_DAY_CLOSE_MINUTES)

def test_day_positions_have_an_end_of_day_close():
    """Give day positions a close time, or they'd stay overnight with no stop"""

    assert "day" in END_OF_DAY_CLOSE_MINUTES

def test_stuck_alert_comes_before_the_close():
    """Alert about a stuck close while there's still time to retry before the market closes"""

    assert 0 < CLOSING_ALERT_MINUTES < min(END_OF_DAY_CLOSE_MINUTES.values())

def test_cancel_wait_is_positive():
    """Wait at least a second for cancels"""

    assert CANCEL_WAIT_SECONDS > 0

def test_database_down_at_the_close_alerts_once(monkeypatch):
    """Send one critical alert when the database is down during the end-of-day close, and sell nothing"""
    sent = []
    monkeypatch.setattr("exits.sweep.send_critical", sent.append)
    watch = ExitWatch()

    reports = [run_exits(DownConnection(), None, CALENDAR, (NOW + timedelta(minutes=m)).replace(tzinfo=timezone.utc),
                         watch) for m in range(3)]

    assert {report.status for report in reports} == {"database_down"}
    assert len(sent) == 1

def test_database_down_before_the_close_doesnt_alert(monkeypatch):
    """Stay quiet about a down database mid-day; the end-of-day alert is for the close"""
    sent = []
    monkeypatch.setattr("exits.sweep.send_critical", sent.append)

    run_exits(DownConnection(), None, CALENDAR, datetime(2026, 11, 9, 17, 0, tzinfo=timezone.utc), ExitWatch())

    assert sent == []
