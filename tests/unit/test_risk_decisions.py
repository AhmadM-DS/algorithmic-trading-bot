"""
test_risk_decisions.py
Unit tests for RiskRequest and Decision
"""

#Standard Library
from dataclasses import FrozenInstanceError

#Third Party Libraries
import pytest

#Local Imports
from risk.decisions import Decision, RiskRequest
from strategies.signals import Signal

BUY_SIGNAL = Signal(side="buy", time_frame="15Min", holding_type="day", stop_price=196.0,
                    target_price=208.0, reason="test", strategy_version="1.0.0", ticker="AAPL", features={})
"""A valid day-trade buy signal"""

def test_request_rejects_negative_price():
    """Raise when the price is negative"""

    with pytest.raises(ValueError, match="negative"):
        RiskRequest(signal=BUY_SIGNAL, strategy_id=1, price=-1)

def test_request_rejects_zero_price():
    """Raise when the price is 0"""

    with pytest.raises(ValueError, match="zero"):
        RiskRequest(signal=BUY_SIGNAL, strategy_id=2, price=0)

def test_request_rejects_nan_price():
    """Raise when the price is NaN, which slips past a plain <= 0 check"""

    with pytest.raises(ValueError, match="missing price"):
        RiskRequest(signal=BUY_SIGNAL, strategy_id=3, price=float("nan"))

def test_approved_decision_is_created():
    """Accept an approved Decision with no skip reason and no failures"""

    decision = Decision(approved_quantity=2, skip_reason=None, failed_checks=(), sizer="test", sized_quantity=2)

    assert decision.approved_quantity == 2

def test_skipped_decision_is_created():
    """Accept a skipped Decision whose skip reason is its only failure"""

    decision = Decision(approved_quantity=0, skip_reason="daily_halt", failed_checks=("daily_halt",), sizer="test", sized_quantity=0)

    assert decision.skip_reason == "daily_halt"

def test_decision_rejects_negative_quantity():
    """Raise when a quantity is below 0"""

    with pytest.raises(ValueError, match="less than 0"):
        Decision(approved_quantity=-1, skip_reason=None, failed_checks=(), sizer="test", sized_quantity=2)

def test_decision_rejects_approved_with_skip_reason():
    """Raise when an approved Decision has a skip reason"""

    with pytest.raises(ValueError, match="rejected"):
        Decision(approved_quantity=15, skip_reason="daily_halt", failed_checks=("daily_halt",), sizer="test", sized_quantity=15)

def test_decision_rejects_skipped_without_skip_reason():
    """Raise when a skipped Decision has no skip reason"""

    with pytest.raises(ValueError, match="rejected"):
        Decision(approved_quantity=0, skip_reason=None, failed_checks=(), sizer="test", sized_quantity=0)

def test_decision_rejects_skip_reason_not_first_failed_check():
    """Raise when the skip reason isn't the highest-priority failure"""

    with pytest.raises(ValueError, match="top failure"):
        Decision(approved_quantity=0, skip_reason="shadow", failed_checks=("daily_halt", "shadow"), sizer="test", sized_quantity=0)

def test_decision_rejects_skipped_with_no_failed_checks():
    """Raise when a skipped Decision lists no failures"""

    with pytest.raises(ValueError, match="top failure"):
        Decision(approved_quantity=0, skip_reason="daily_halt", failed_checks=(), sizer="test", sized_quantity=0)

def test_decision_rejects_approved_above_sized():
    """Raise when the guardrails approved more than the sizer wanted"""

    with pytest.raises(ValueError, match="more than"):
        Decision(approved_quantity=10, skip_reason=None, failed_checks=(), sizer="test", sized_quantity=3)

def test_decision_rejects_approved_with_failed_checks():
    """Raise when an approved Decision lists failures"""

    with pytest.raises(ValueError, match="has failed_checks"):
        Decision(approved_quantity=10, skip_reason=None, failed_checks=("shadow",), sizer="test", sized_quantity=10)

def test_decision_cannot_be_changed():
    """Block changing a field after the Decision is made"""
    decision = Decision(approved_quantity=2, skip_reason=None, failed_checks=(), sizer="test", sized_quantity=2)

    with pytest.raises(FrozenInstanceError, match="cannot assign to field"):
        decision.approved_quantity = 1
