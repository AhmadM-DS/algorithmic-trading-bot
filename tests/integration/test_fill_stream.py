"""
test_fill_stream.py
Integration tests for fills.stream.FillStream: one message in, rows and alerts out, never a crash
"""

#Standard Library
from decimal import Decimal

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from execution.broker import BrokerOrder, BrokerUnavailable
from fill_samples import CommitCounter, add_bracket, add_strategy, message, positions
from fills.stream import FillStream

class KeepOpen(CommitCounter):
    """The test connection, which the stream may 'close' without ending the test's transaction"""

    def close(self):
        pass

class BrokenConnection:
    """A connection whose every query fails, like a database that went away"""

    def cursor(self):
        raise pyodbc.OperationalError("08S01", "communication link failure")

    def close(self):
        pass

class SilentBroker:
    """A broker with nothing to report"""

    def get_fill_activities(self, since):
        return []

    def get_order(self, alpaca_order_id):
        return None

class LegsCanceled(SilentBroker):
    """A broker reporting every looked-up order as canceled"""

    def get_order(self, alpaca_order_id):
        return BrokerOrder(alpaca_order_id, "leg", "sell", "limit", "day", "canceled", 10, 0, None, None,
                           Decimal("5.20"))

class DownBroker(SilentBroker):
    """A broker Alpaca isn't answering for"""

    def get_fill_activities(self, since):
        raise BrokerUnavailable("No answer from Alpaca: read timed out")

@pytest.fixture
def sent():
    return []

def make_stream(conn, sent, broker=None):
    channels = {"critical": lambda text: sent.append(("critical", text)),
                "trades": lambda text: sent.append(("trades", text))}
    return FillStream(broker or SilentBroker(), connect=lambda: conn, alert_channels=channels)

def test_message_is_saved_and_handled(bot_conn, sent):
    """Turn a stream fill into its raw row, trade and position with no alerts"""
    add_bracket(bot_conn, add_strategy(bot_conn))
    stream = make_stream(KeepOpen(bot_conn), sent)

    stream.handle_message(message("fill", "alpaca-buy-1", status="filled", filled=10, average="5.01",
                                  execution_id="exec-buy-1", fill_quantity=10, price="5.01"))

    assert (len(positions(bot_conn)), sent) == (1, [])

def test_unreadable_message_is_kept_raw_and_alerted(bot_conn, sent):
    """Save a message the parser can't read, raw, and send one critical alert"""
    stream = make_stream(KeepOpen(bot_conn), sent)

    stream.handle_message({"event": "something_new", "execution_id": "x-1"})

    saved = bot_conn.execute("SELECT event_type, raw_json FROM broker_events WHERE execution_id = 'x-1'").fetchone()
    assert (saved.event_type, "something_new" in saved.raw_json) == ("something_new", True)
    assert [channel for channel, _ in sent] == ["critical"]

def test_database_outage_alerts_and_keeps_listening(sent):
    """Alert and drop the connection instead of raising when the database is unreachable"""
    stream = make_stream(BrokenConnection(), sent)

    stream.handle_message(message("fill", "alpaca-buy-1", status="filled", filled=10, execution_id="exec-1",
                                  fill_quantity=10, price="5.01"))

    assert stream.stream_conn is None
    assert sent[0][0] == "critical" and "catch-up" in sent[0][1]

def test_each_alert_is_sent_once_per_run(sent):
    """Send a repeated alert (a fill retried every minute) only the first time"""
    stream = make_stream(BrokenConnection(), sent)

    stream.send_alerts([("critical", "same problem")])
    stream.send_alerts([("critical", "same problem")])

    assert sent == [("critical", "same problem")]

def test_catch_up_that_finds_something_is_logged_as_a_bot_event(bot_conn, sent):
    """Write a fill_catch_up bot_events row when the catch-up recorded anything"""
    add_bracket(bot_conn, add_strategy(bot_conn))
    stream = make_stream(KeepOpen(bot_conn), sent)
    stream.handle_message(message("fill", "alpaca-buy-1", status="filled", filled=10, execution_id="exec-1",
                                  fill_quantity=10, price="5.01"))

    make_stream(KeepOpen(bot_conn), sent, LegsCanceled()).catch_up_once()

    event = bot_conn.execute("SELECT details FROM bot_events WHERE event_type = 'fill_catch_up'").fetchone()
    assert "2 status changes" in event.details

def test_catch_up_with_alpaca_down_only_logs(bot_conn, sent):
    """Skip the catch-up quietly when Alpaca doesn't answer; the next one tries again"""
    stream = make_stream(KeepOpen(bot_conn), sent, DownBroker())

    stream.catch_up_once()

    assert sent == []
