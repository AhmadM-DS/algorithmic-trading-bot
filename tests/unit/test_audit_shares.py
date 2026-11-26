"""
test_audit_shares.py
Unit tests for the share comparison and A2's settings
"""

#Local Imports
from audit import ShareCounts, compare_shares, database_shares
from config.constants import (CATCH_UP_SECONDS, RECONCILIATION_FAILED_CHECKS, RECONCILIATION_REPEAT_MINUTES,
                              RECONCILIATION_WAIT_SECONDS, UNKNOWN_ORDER_WAIT_SECONDS)
from risk.context import OpenPosition

def _position(strategy_id, ticker, shares, position_id=1):
    """Build one open position"""
    return OpenPosition(position_id=position_id, strategy_id=strategy_id, ticker=ticker, holding_type="day",
                        shares_held=shares, avg_entry_price=10.0)

def test_wait_outlasts_a_manual_trade_being_recorded():
    """Wait longer than A1 can take to record a manual trade (180 s wait + one 60 s catch-up), so it never alerts"""
    assert RECONCILIATION_WAIT_SECONDS >= UNKNOWN_ORDER_WAIT_SECONDS + CATCH_UP_SECONDS

def test_alert_repeats_and_failure_limit_are_positive():
    """Keep the repeat period and the failed-check limit above 0"""
    assert RECONCILIATION_REPEAT_MINUTES > 0 and RECONCILIATION_FAILED_CHECKS > 0

def test_matching_counts_are_not_a_mismatch():
    """Report nothing when Alpaca and the database hold the same shares"""

    mismatches = compare_shares({"AAPL": 10}, {"AAPL": 10})

    assert mismatches == {}

def test_different_counts_are_a_mismatch():
    """Report both counts for a ticker held in different amounts"""

    mismatches = compare_shares({"ABC": 70}, {"ABC": 100})

    assert mismatches == {"ABC": ShareCounts(alpaca=70, database=100)}

def test_shares_only_at_alpaca_are_a_mismatch():
    """Count a ticker the database doesn't know as 0 shares in the database"""

    mismatches = compare_shares({"ABC": 5}, {})

    assert mismatches == {"ABC": ShareCounts(alpaca=5, database=0)}

def test_shares_only_in_the_database_are_a_mismatch():
    """Count a ticker Alpaca doesn't hold as 0 shares at Alpaca"""

    mismatches = compare_shares({}, {"ABC": 5})

    assert mismatches == {"ABC": ShareCounts(alpaca=0, database=5)}

def test_short_at_alpaca_is_always_a_mismatch():
    """Report a short even if the database shows the same negative count"""

    mismatches = compare_shares({"ABC": -3}, {"ABC": -3})

    assert mismatches["ABC"].short

def test_only_mismatched_tickers_are_reported():
    """Leave matching tickers out when another ticker differs"""

    mismatches = compare_shares({"AAPL": 10, "ABC": 70}, {"AAPL": 10, "ABC": 100})

    assert list(mismatches) == ["ABC"]

def test_database_shares_sum_every_strategy_holding_a_ticker():
    """Add up the positions of all strategies (manual included) in one ticker, as Alpaca keeps one count per ticker"""
    positions = [_position(3, "ABC", 50, 1), _position(4, "ABC", 50, 2), _position(1, "XYZ", 5, 3)]

    totals = database_shares(positions)

    assert totals == {"ABC": 100, "XYZ": 5}

def test_option_held_at_alpaca_is_not_a_share_mismatch():
    """Leave a held option out of the share check: the database can't hold it (BUG-26), so it would mismatch every
    cycle"""
    mismatches = compare_shares({"AAPL": 10, "AAPL261120C00150000": 1}, {"AAPL": 10})

    assert mismatches == {}
