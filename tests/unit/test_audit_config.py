"""
test_audit_config.py
Unit tests for the end-of-day audit's settings
"""

#Local Imports
from config.constants import (ACTIVITY_LOOKBACK_DAYS, AUDIT_CATCH_UP_MAX_DAYS, AUDIT_MINUTES_AFTER_CLOSE,
                              AUDIT_REPEAT_MINUTES, CASH_TOLERANCE, CATCH_UP_SECONDS, UNKNOWN_ORDER_WAIT_SECONDS)

def test_audit_waits_until_the_last_manual_fill_is_booked():
    """Start the audit after the fill stream has booked a manual trade made at the close (wait + one catch-up)"""

    assert AUDIT_MINUTES_AFTER_CLOSE * 60 >= UNKNOWN_ORDER_WAIT_SECONDS + CATCH_UP_SECONDS

def test_catch_up_reaches_at_least_as_far_back_as_the_activity_lookback():
    """Cap the catch-up at no fewer days than the late-activity lookback, so a re-pull never skips a day"""

    assert 1 <= ACTIVITY_LOOKBACK_DAYS <= AUDIT_CATCH_UP_MAX_DAYS

def test_repeat_and_tolerance_are_positive():
    """Repeat the reminder at a positive interval and allow only rounding-sized cash differences"""

    assert AUDIT_REPEAT_MINUTES > 0
    assert 0 < CASH_TOLERANCE < 1
