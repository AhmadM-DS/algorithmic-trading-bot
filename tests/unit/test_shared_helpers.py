"""
test_shared_helpers.py
Unit tests for the helpers several packages share: one UNREADABLE_ERRORS tuple and ChangeLog (log once on change)
"""

#Standard Library
import logging

#Local Imports
import errors
import fills.events
import notifications.discord
import notifications.failed
from logger import ChangeLog

LOG = logging.getLogger("test_change_log")

def test_every_package_uses_the_one_unreadable_errors_tuple():
    """Read outside data with the same exception tuple everywhere, so the lists can't drift apart"""

    tuples = [fills.events.UNREADABLE_ERRORS, notifications.discord.UNREADABLE_ERRORS,
              notifications.failed.UNREADABLE_ERRORS]

    assert all(found is errors.UNREADABLE_ERRORS for found in tuples)

def test_failure_is_logged_once_until_it_recovers(caplog):
    """Log a failing key once, however often it fails, and report whether this call logged"""
    changes = ChangeLog(LOG)

    with caplog.at_level(logging.INFO, logger="test_change_log"):
        first, second = changes.failed("disk", "disk failed"), changes.failed("disk", "disk failed")

    assert (first, second, caplog.text.count("disk failed")) == (True, False, 1)

def test_recovery_is_logged_only_after_a_failure(caplog):
    """Log a recovery once, and never for a key that wasn't failing"""
    changes = ChangeLog(LOG)
    changes.failed("disk", "disk failed")

    with caplog.at_level(logging.INFO, logger="test_change_log"):
        results = [changes.recovered("disk", "disk back"), changes.recovered("disk", "disk back"),
                   changes.recovered("cpu", "cpu back")]

    assert results == [True, False, False]
    assert caplog.text.count("back") == 1

def test_keys_are_independent():
    """Track each key on its own, so one recovering doesn't clear another"""
    changes = ChangeLog(LOG)
    changes.failed("bot", "bot failed")
    changes.failed("webhook", "webhook failed")

    changes.recovered("webhook", "webhook back")

    assert ("bot" in changes, "webhook" in changes) == (True, False)

def test_clear_forgets_every_failure():
    """Start fresh after clear, so the next failure is logged again"""
    changes = ChangeLog(LOG)
    changes.failed("line 3", "bad line")

    changes.clear()

    assert changes.failed("line 3", "bad line") is True
