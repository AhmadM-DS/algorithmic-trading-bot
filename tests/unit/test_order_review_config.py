"""
test_order_review_config.py
Unit tests for E2's settings and the shared skip priority list
"""

#Local Imports
from config.constants import (ENABLED_HOLDING_TYPES, LAST_BUY_MINUTES_BEFORE_CLOSE, MAX_PRICE_MOVE_OF_STOP,
                              SKIP_PRIORITY)
from order_review.checks import BUY_CHECKS

def test_every_enabled_holding_type_has_buy_checks():
    assert set(ENABLED_HOLDING_TYPES) <= set(BUY_CHECKS)

def test_last_buy_times_fit_in_a_trading_day():
    """Keep each cutoff above 0 and under a full 6.5-hour session"""
    assert all(0 < minutes < 390 for minutes in LAST_BUY_MINUTES_BEFORE_CLOSE.values())

def test_max_price_move_is_a_share_of_the_stop_distance():
    """Allow only part of the way to the stop, so a moved price can never already be past it"""
    assert 0 < MAX_PRICE_MOVE_OF_STOP < 1

def test_skip_priority_has_no_repeats():
    assert len(SKIP_PRIORITY) == len(set(SKIP_PRIORITY))

def test_order_checks_rank_after_every_risk_buy_code():
    """Rank E2's codes after risk's buy codes, as agreed in R1"""
    order_codes = ("market_closed", "too_late_to_buy", "not_tradable", "open_order", "stale_price", "price_moved")
    assert min(SKIP_PRIORITY.index(code) for code in order_codes) > SKIP_PRIORITY.index("invalid_exit_prices")
