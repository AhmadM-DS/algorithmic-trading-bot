"""
test_audit_watch.py
Unit tests for ReconciliationWatch (mismatch clocks, alert repeats, failed checks) and AuditWatch (reminders,
outages)
"""

#Standard Library
from datetime import datetime, timedelta, timezone

#Local Imports
from audit import AuditWatch, ReconciliationWatch

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

AUDIT_OPEN = datetime(2026, 11, 3, 14, 31, tzinfo=timezone.utc)

def test_first_reminder_is_due_at_once():
    """Remind on the first check when nothing has gone out yet (also after a restart)"""

    assert AuditWatch().reminder_due(AUDIT_OPEN, 60) is True

def test_reminder_repeats_after_exactly_the_interval():
    """Stay quiet within the interval and remind again once it has fully passed"""
    watch = AuditWatch()
    watch.reminded(AUDIT_OPEN)

    due = [watch.reminder_due(AUDIT_OPEN + timedelta(minutes=minutes), 60) for minutes in (59, 60)]

    assert due == [False, True]

def test_reminder_is_due_on_a_new_new_york_day():
    """Remind at the first check of a new New York day even if the interval hasn't passed"""
    watch = AuditWatch()
    watch.reminded(datetime(2026, 11, 3, 20, 59, tzinfo=timezone.utc))

    assert watch.reminder_due(datetime(2026, 11, 4, 14, 30, tzinfo=timezone.utc), 1000) is True

def test_outage_alerts_once_per_cause_and_recovery_clears_all():
    """Alert the first outage of each cause, then say the audit runs again once, after any outage"""
    watch = AuditWatch()

    first = [watch.outage("alpaca"), watch.outage("alpaca"), watch.outage("database")]

    assert first == [True, False, True]
    assert (watch.recovered(), watch.recovered()) == (True, False)

def test_recovery_of_some_causes_keeps_the_others():
    """Clear only the causes that are over, so a day still failing keeps its outage (and its alert) open"""
    watch = AuditWatch()
    watch.outage("alpaca")
    watch.outage("data")

    recovered = watch.recovered(("alpaca", "database"))

    assert (recovered, watch.outage("data"), watch.recovered(("alpaca",))) == (True, False, False)
