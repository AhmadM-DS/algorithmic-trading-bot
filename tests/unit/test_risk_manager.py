"""
test_risk_manager.py
Unit tests for the guardrail lists in manager.py
"""

#Standard Library
from datetime import datetime, timezone
import logging

#Local Imports
from risk.context import RiskContext, StrategyState
from risk.decisions import RiskRequest
from risk.manager import GUARDRAILS, decide
from strategies.signals import Signal

DAY_PRIORITY = ["check_mode", "check_kill_switch", "check_drawdown", "check_daily_halt", "check_leverage",
                "check_buying_power", "check_budget", "check_max_positions", "check_ticker_exposure",
                "check_positions_per_ticker", "check_cooldown", "check_quantity", "check_order_size"]
"""The day guardrails in the agreed priority order (redesign plan, R1 and R2 decisions)"""

def test_day_guardrails_follow_priority_order():
    """Keep the day guardrails in priority order, since failed_checks[0] becomes the skip reason"""

    names = [check.__name__ for check in GUARDRAILS["day"]]

    assert names == DAY_PRIORITY

def test_only_day_rules_exist_yet():
    """Have rules only for day trades until swing rules are built (RISK-8)"""

    holding_types = list(GUARDRAILS)

    assert holding_types == ["day"]

def test_zero_quantity_logs_budget_slot_buying_power_and_price(caplog):
    """Log why a $70 share was skipped: it costs more than the $50 slot of a $250 budget"""
    signal = Signal(side="buy", time_frame="15Min", holding_type="day", stop_price=None, target_price=None,
                    reason="test", strategy_version="1.0.0", ticker="AAPL", features={})
    context = RiskContext(as_of=datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc), equity=1000.0,
                          buying_power=4000.0, open_positions=(), recent_exits=(), broker_positions=(),
                          strategies=(StrategyState(strategy_id=3, mode="live", effective_budget=250.0,
                                                    name="momentum"),))

    with caplog.at_level(logging.INFO, logger="trades"):
        decide(RiskRequest(signal=signal, strategy_id=3, price=70.0), context)

    assert "zero_quantity: momentum AAPL costs $70.00 a share, more than its slot of $50.00 (budget $250.00, "            "buying power $4000.00)" in caplog.text
