"""
test_reconciliation_storage.py
Integration tests for storage/reconciliation.py: mismatch and resolved rows in bot_events
"""

#Standard Library
import json

#Third Party Libraries
import pytest

#Local Imports
from risk_samples import events
from storage.reconciliation import MISMATCH, RESOLVED, get_open_mismatches, insert_reconciliation_event

def test_mismatch_details_are_saved_as_json(bot_conn):
    """Save the ticker and both counts as JSON in details"""

    insert_reconciliation_event(bot_conn, MISMATCH, "ABC", 70, 100)

    assert json.loads(events(bot_conn, MISMATCH)[0].details) == {"ticker": "ABC", "alpaca": 70, "database": 100}

def test_json_details_can_be_read_in_sql(bot_conn):
    """Let SQL (and Power BI) read the counts with JSON_VALUE"""
    insert_reconciliation_event(bot_conn, MISMATCH, "ABC", 70, 100)

    row = bot_conn.execute("SELECT JSON_VALUE(details, '$.ticker'), CAST(JSON_VALUE(details, '$.alpaca') AS INT) "
                           "FROM bot_events WHERE event_type = ?", MISMATCH).fetchone()

    assert tuple(row) == ("ABC", 70)

def test_unknown_event_type_is_refused(bot_conn):
    """Refuse an event type that isn't a reconciliation row"""

    with pytest.raises(ValueError, match="Unknown reconciliation event"):
        insert_reconciliation_event(bot_conn, "kill_switch", "ABC", 70, 100)

def test_recorded_mismatch_is_open(bot_conn):
    """Return a mismatch with no resolved row after it, with its saved counts"""
    insert_reconciliation_event(bot_conn, MISMATCH, "ABC", 70, 100)

    open_mismatches = get_open_mismatches(bot_conn)

    assert (open_mismatches["ABC"]["alpaca"], open_mismatches["ABC"]["database"]) == (70, 100)

def test_resolved_mismatch_is_not_open(bot_conn):
    """Leave out a mismatch whose newest row is resolved"""
    insert_reconciliation_event(bot_conn, MISMATCH, "ABC", 70, 100)
    insert_reconciliation_event(bot_conn, RESOLVED, "ABC", 100, 100)

    open_mismatches = get_open_mismatches(bot_conn)

    assert "ABC" not in open_mismatches

def test_new_mismatch_after_a_resolve_is_open_with_new_counts(bot_conn):
    """Return the newest mismatch when a ticker mismatches again after being resolved"""
    insert_reconciliation_event(bot_conn, MISMATCH, "ABC", 70, 100)
    insert_reconciliation_event(bot_conn, RESOLVED, "ABC", 100, 100)
    insert_reconciliation_event(bot_conn, MISMATCH, "ABC", 40, 100)

    open_mismatches = get_open_mismatches(bot_conn)

    assert open_mismatches["ABC"]["alpaca"] == 40

def test_each_ticker_is_resolved_on_its_own(bot_conn):
    """Keep one ticker open when only another ticker's mismatch was resolved"""
    insert_reconciliation_event(bot_conn, MISMATCH, "ABC", 70, 100)
    insert_reconciliation_event(bot_conn, MISMATCH, "XYZ", 0, 5)
    insert_reconciliation_event(bot_conn, RESOLVED, "XYZ", 5, 5)

    open_mismatches = get_open_mismatches(bot_conn)

    assert list(open_mismatches) == ["ABC"]
