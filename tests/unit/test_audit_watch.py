"""
test_audit_watch.py
Unit tests for ReconciliationWatch: mismatch clocks, alert repeats and failed checks
"""

#Standard Library
from datetime import datetime, timedelta

#Local Imports
from audit import ReconciliationWatch

NOW = datetime(2026, 11, 11, 15, 0)
"""A fixed naive UTC time so no test depends on the clock"""

def test_seen_keeps_the_first_time():
    """Keep the clock running from the first sighting, not the latest"""
    watch = ReconciliationWatch()
    watch.seen("ABC", NOW)

    since = watch.seen("ABC", NOW + timedelta(minutes=2))

    assert since == NOW

def test_forget_restarts_the_clock():
    """Start a new clock for a ticker whose earlier mismatch cleared"""
    watch = ReconciliationWatch()
    watch.seen("ABC", NOW)
    watch.forget("ABC")

    since = watch.seen("ABC", NOW + timedelta(minutes=10))

    assert since == NOW + timedelta(minutes=10)

def test_repeat_waits_a_full_period_after_the_last_alert():
    """Hold the repeat until 60 minutes after the last alert"""
    watch = ReconciliationWatch()
    watch.alerted("ABC", NOW)

    due = watch.repeat_due("ABC", NOW - timedelta(hours=3), NOW + timedelta(minutes=59), 60)

    assert not due

def test_repeat_is_due_after_a_full_period():
    """Repeat once 60 minutes have passed since the last alert"""
    watch = ReconciliationWatch()
    watch.alerted("ABC", NOW)

    due = watch.repeat_due("ABC", NOW, NOW + timedelta(minutes=60), 60)

    assert due

def test_repeat_after_a_restart_counts_from_the_recorded_time():
    """Use the row's time as the last alert when the watch is new (after a restart)"""
    watch = ReconciliationWatch()

    due = watch.repeat_due("ABC", NOW - timedelta(minutes=90), NOW, 60)

    assert due

def test_failed_checks_alert_once_at_the_limit():
    """Return True only on the third failure in a row, not before or after"""
    watch = ReconciliationWatch()

    results = [watch.check_failed(3) for _ in range(5)]

    assert results == [False, False, True, False, False]

def test_check_ran_resets_the_failed_count():
    """Start counting again from 0 after a check that ran"""
    watch = ReconciliationWatch()
    watch.check_failed(3)
    watch.check_failed(3)
    watch.check_ran()

    alerted = watch.check_failed(3)

    assert not alerted and watch.failed_checks == 1

def test_check_ran_reports_a_recovery_only_after_an_alert():
    """Return True after the failure alert went out, False if it never did"""
    watch = ReconciliationWatch()
    quiet = watch.check_ran()
    for _ in range(3):
        watch.check_failed(3)

    recovered = watch.check_ran()

    assert (quiet, recovered) == (False, True)
