"""
test_reconciliation.py
Scenario tests for audit/reconciliation.py on noctis_test: late fills, manual trades, real mismatches, restarts
"""

#Standard Library
import json
from datetime import timedelta, timezone

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from audit import ReconciliationWatch, compare_shares, reconcile, reconcile_failed
from fill_samples import CommitCounter
from risk import BrokerPosition, OpenPosition, RiskContext, StrategyState
from risk_samples import db_now, events
from storage.reconciliation import MISMATCH, RESOLVED

class AlertRecorder:
    """Stands in for Discord: keeps each alert with how many commits had happened when it was sent"""

    def __init__(self, conn):
        self.conn = conn
        self.sent = []

    def __call__(self, message):
        self.sent.append((message, self.conn.commits))

    @property
    def messages(self):
        return [message for message, _ in self.sent]

class BrokenConnection:
    """Stands in for a connection to a database that stopped answering"""

    def cursor(self):
        raise pyodbc.OperationalError("08S01", "Communication link failure")

    def rollback(self):
        raise pyodbc.OperationalError("08S01", "Communication link failure")

@pytest.fixture
def conn(bot_conn):
    """The bot connection, with commits counted instead of made"""
    return CommitCounter(bot_conn)

@pytest.fixture
def alerts(conn):
    return AlertRecorder(conn)

@pytest.fixture
def start(conn):
    """The database's now, so the fake clock lines up with the times rows are saved at"""
    return db_now(conn)

def cycle(at, alpaca=None, database=None):
    """Build the snapshot one cycle sees: Alpaca's counts and one open position per ticker in the database"""
    alpaca, database = alpaca or {}, database or {}
    positions = tuple(OpenPosition(position_id=i, strategy_id=3, ticker=ticker, holding_type="day", shares_held=shares,
                                   avg_entry_price=10.0) for i, (ticker, shares) in enumerate(database.items()))
    return RiskContext(as_of=at.replace(tzinfo=timezone.utc), equity=1000.0, buying_power=1000.0,
                       strategies=(StrategyState(strategy_id=3, mode="live", effective_budget=250.0),),
                       open_positions=positions, recent_exits=(),
                       broker_positions=tuple(BrokerPosition(ticker, shares) for ticker, shares in alpaca.items()),
                       share_mismatches=compare_shares(alpaca, database))

def seconds(start, count):
    return start + timedelta(seconds=count)

MATCHED = {"alpaca": {"ABC": 100}, "database": {"ABC": 100}}
"""Alpaca and the database agree on 100 ABC"""

OFF_BY_30 = {"alpaca": {"ABC": 70}, "database": {"ABC": 100}}
"""Alpaca holds 70 ABC, the database thinks 100"""

def test_fill_saved_late_blocks_quietly_and_leaves_nothing(conn, alerts, start):
    """Block ABC for the one cycle the database lags, then lift it with no row and no alert"""
    watch = ReconciliationWatch()

    first = reconcile(conn, cycle(start, {"ABC": 105}, {"ABC": 100}), watch, alerts)
    second = reconcile(conn, cycle(seconds(start, 1), {"ABC": 105}, {"ABC": 105}), watch, alerts)

    assert (first.blocked, second.blocked) == (("ABC",), ())
    assert (events(conn, MISMATCH), alerts.sent, watch.first_seen) == ([], [], {})

def test_manual_trade_recorded_at_240_seconds_never_alerts(conn, alerts, start):
    """Stay quiet through a manual buy that A1 records after its 180 s wait plus one 60 s catch-up"""
    watch = ReconciliationWatch()

    for second in range(0, 241, 60):
        reconcile(conn, cycle(seconds(start, second), {"ABC": 1}), watch, alerts)
    reconcile(conn, cycle(seconds(start, 250), {"ABC": 1}, {"ABC": 1}), watch, alerts)

    assert (events(conn, MISMATCH), alerts.sent) == ([], [])

def test_mismatch_is_not_recorded_before_the_wait(conn, alerts, start):
    """Save nothing for a mismatch seen for 299 seconds"""
    watch = ReconciliationWatch()
    reconcile(conn, cycle(start, **OFF_BY_30), watch, alerts)

    report = reconcile(conn, cycle(seconds(start, 299), **OFF_BY_30), watch, alerts)

    assert (report.recorded, events(conn, MISMATCH)) == ((), [])

def test_mismatch_is_recorded_after_the_wait(conn, alerts, start):
    """Save one mismatch row with both counts once it has lasted 300 seconds"""
    watch = ReconciliationWatch()
    reconcile(conn, cycle(start, **OFF_BY_30), watch, alerts)

    report = reconcile(conn, cycle(seconds(start, 300), **OFF_BY_30), watch, alerts)

    rows = events(conn, MISMATCH)
    assert report.recorded == ("ABC",)
    assert [json.loads(row.details) for row in rows] == [{"ticker": "ABC", "alpaca": 70, "database": 100}]

def test_recorded_mismatch_alerts_after_the_commit(conn, alerts, start):
    """Send the critical alert only once the row is committed, naming both counts"""
    watch = ReconciliationWatch()
    reconcile(conn, cycle(start, **OFF_BY_30), watch, alerts)

    reconcile(conn, cycle(seconds(start, 300), **OFF_BY_30), watch, alerts)

    assert len(alerts.sent) == 1
    message, commits = alerts.sent[0]
    assert "ABC: Alpaca 70, database 100" in message and commits == 1

def test_recorded_mismatch_is_not_saved_again(conn, alerts, start):
    """Keep one row and one alert while the mismatch stays inside the hour"""
    watch = ReconciliationWatch()
    for second in (0, 300, 360, 1800):
        reconcile(conn, cycle(seconds(start, second), **OFF_BY_30), watch, alerts)

    assert (len(events(conn, MISMATCH)), len(alerts.sent)) == (1, 1)

def test_recorded_mismatch_alert_repeats_every_hour(conn, alerts, start):
    """Repeat the alert 60 minutes after the first one, without a new row"""
    watch = ReconciliationWatch()
    for second in (0, 300, 300 + 3599):
        reconcile(conn, cycle(seconds(start, second), **OFF_BY_30), watch, alerts)

    report = reconcile(conn, cycle(seconds(start, 300 + 3600), **OFF_BY_30), watch, alerts)

    assert report.repeated == ("ABC",)
    assert (len(events(conn, MISMATCH)), len(alerts.sent)) == (1, 2)
    assert alerts.messages[1].startswith("Still a share mismatch on ABC")

def test_matching_counts_resolve_a_recorded_mismatch(conn, alerts, start):
    """Save a resolved row with the matching counts and send one alert when the counts agree again"""
    watch = ReconciliationWatch()
    reconcile(conn, cycle(start, **OFF_BY_30), watch, alerts)
    reconcile(conn, cycle(seconds(start, 300), **OFF_BY_30), watch, alerts)

    report = reconcile(conn, cycle(seconds(start, 400), **MATCHED), watch, alerts)

    assert report.resolved == ("ABC",)
    assert json.loads(events(conn, RESOLVED)[0].details) == {"ticker": "ABC", "alpaca": 100, "database": 100}
    assert "ABC resolved" in alerts.messages[-1]

def test_resolved_mismatch_is_left_alone_afterwards(conn, alerts, start):
    """Do nothing more once a mismatch is resolved"""
    watch = ReconciliationWatch()
    for second, counts in ((0, OFF_BY_30), (300, OFF_BY_30), (400, MATCHED)):
        reconcile(conn, cycle(seconds(start, second), **counts), watch, alerts)

    report = reconcile(conn, cycle(seconds(start, 460), **MATCHED), watch, alerts)

    assert (report.resolved, len(events(conn, RESOLVED)), len(alerts.sent)) == ((), 1, 2)

def test_restart_does_not_save_a_recorded_mismatch_twice(conn, alerts, start):
    """Read the open mismatch back after a restart instead of recording it again"""
    before = ReconciliationWatch()
    reconcile(conn, cycle(start, **OFF_BY_30), before, alerts)
    reconcile(conn, cycle(seconds(start, 300), **OFF_BY_30), before, alerts)
    restarted = ReconciliationWatch()

    for second in (600, 900, 1200):
        reconcile(conn, cycle(seconds(start, second), **OFF_BY_30), restarted, alerts)

    assert (len(events(conn, MISMATCH)), len(alerts.sent)) == (1, 1)

def test_restart_still_resolves_a_recorded_mismatch(conn, alerts, start):
    """Resolve a mismatch recorded before the restart once the counts match after it"""
    watch = ReconciliationWatch()
    reconcile(conn, cycle(start, **OFF_BY_30), watch, alerts)
    reconcile(conn, cycle(seconds(start, 300), **OFF_BY_30), watch, alerts)

    report = reconcile(conn, cycle(seconds(start, 600), **MATCHED), ReconciliationWatch(), alerts)

    assert (report.resolved, len(events(conn, RESOLVED))) == (("ABC",), 1)

def test_short_at_alpaca_is_recorded_and_named(conn, alerts, start):
    """Record a short the database doesn't know and say so in the alert"""
    watch = ReconciliationWatch()
    reconcile(conn, cycle(start, {"ABC": -3}), watch, alerts)

    reconcile(conn, cycle(seconds(start, 300), {"ABC": -3}), watch, alerts)

    assert "Alpaca shows a short" in alerts.messages[0]

def test_one_tickers_mismatch_leaves_others_unblocked(conn, alerts, start):
    """Block only the mismatched ticker; a matching ticker is left out"""
    watch = ReconciliationWatch()

    report = reconcile(conn, cycle(start, {"ABC": 70, "XYZ": 5}, {"ABC": 100, "XYZ": 5}), watch, alerts)

    assert report.blocked == ("ABC",)

def test_third_failed_check_alerts_once(alerts):
    """Alert on the third check in a row that couldn't run, not on the first two or the fourth"""
    watch = ReconciliationWatch()

    results = [reconcile_failed(watch, RuntimeError("snapshot failed"), alerts) for _ in range(4)]

    assert results == [False, False, True, False]
    assert "couldn't run 3 times in a row" in alerts.messages[0]

def test_check_after_failures_says_it_is_running_again(conn, alerts, start):
    """Send one recovery alert on the first check that runs after the failure alert"""
    watch = ReconciliationWatch()
    for _ in range(3):
        reconcile_failed(watch, RuntimeError("snapshot failed"), alerts)

    reconcile(conn, cycle(start, **MATCHED), watch, alerts)

    assert alerts.messages[-1] == "Share reconciliation is running again."

def test_database_error_counts_as_a_failed_check(alerts, start):
    """Report "failed", keep the block, and count the check when the database doesn't answer"""
    watch = ReconciliationWatch()

    report = reconcile(BrokenConnection(), cycle(start, **OFF_BY_30), watch, alerts)

    assert (report.status, report.blocked, watch.failed_checks) == ("failed", ("ABC",), 1)
