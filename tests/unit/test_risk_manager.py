"""
test_risk_manager.py
Unit tests for the guardrail lists in manager.py
"""

#Local Imports
from risk.manager import GUARDRAILS

DAY_PRIORITY = ["check_mode", "check_leverage", "check_buying_power", "check_budget", "check_max_positions",
                "check_ticker_exposure", "check_positions_per_ticker", "check_cooldown", "check_quantity",
                "check_order_size"]
"""The day guardrails in the agreed priority order (redesign plan, R1 decisions)"""

def test_day_guardrails_follow_priority_order():
    """Keep the day guardrails in priority order, since failed_checks[0] becomes the skip reason"""

    names = [check.__name__ for check in GUARDRAILS["day"]]

    assert names == DAY_PRIORITY

def test_only_day_rules_exist_yet():
    """Have rules only for day trades until swing rules are built (RISK-8)"""

    holding_types = list(GUARDRAILS)

    assert holding_types == ["day"]
