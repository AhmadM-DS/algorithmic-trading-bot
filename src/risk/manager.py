"""
manager.py
Decide every buy and sell: the one function the rest of the bot calls
"""

#Local Imports
from config.constants import POSITION_SIZER
from risk.context import RiskContext
from risk.decisions import Decision, RiskRequest
from risk.guardrails import (check_budget, check_buying_power, check_cooldown, check_leverage, check_max_positions,
                             check_mode, check_order_size, check_positions_per_ticker, check_quantity,
                             check_ticker_exposure)
from risk.sizers import SIZERS

GUARDRAILS = {
    "day": (
        check_mode,
        check_leverage,
        check_buying_power,
        check_budget,
        check_max_positions,
        check_ticker_exposure,
        check_positions_per_ticker,
        check_cooldown,
        check_quantity,
        check_order_size,
    ),
}

def decide(request: RiskRequest, context: RiskContext) -> Decision:
    """Return how many shares to trade for a signal, or why none

    Buys are sized by POSITION_SIZER, then checked by every guardrail for their holding type, in priority order.
    Sells skip the guardrails so a halt can never trap a position; they sell what both the database and Alpaca hold.

    Parameters:
        request (RiskRequest): The signal asking to trade
        context (RiskContext): This cycle's snapshot

    Returns:
        The Decision

    Raises:
        ValueError if the side or holding type has no rules
    """
    side = request.signal.side
    if side == "sell":
        return _decide_sell(request, context)
    if side == "buy":
        return _decide_buy(request, context)
    raise ValueError(f"Unknown side {side!r}. Expected 'buy' or 'sell'")

def _decide_buy(request: RiskRequest, context: RiskContext) -> Decision:
    """Size a buy, then run every guardrail and collect each failure in priority order"""
    holding_type = request.signal.holding_type
    if holding_type not in GUARDRAILS:
        raise ValueError(f"No guardrails for holding type {holding_type!r}. Expected one of {list(GUARDRAILS)}")

    sizer = SIZERS[POSITION_SIZER]
    sizing = sizer.size(request, context)

    failed_checks = []
    for check in GUARDRAILS[holding_type]:
        reason = check(request, context, sizing.quantity)
        if reason is not None:
            failed_checks.append(reason)

    approved = sizing.quantity if not failed_checks else 0
    skip_reason = failed_checks[0] if failed_checks else None
    return Decision(approved_quantity=approved, skip_reason=skip_reason, failed_checks=tuple(failed_checks),
                    sizer=f"{sizer.NAME}:{sizer.VERSION}", sized_quantity=sizing.quantity,
                    parameters=sizing.parameters)

def _decide_sell(request: RiskRequest, context: RiskContext) -> Decision:
    """Sell what this strategy holds, capped by what Alpaca holds so it can never go short"""
    if context.strategy(request.strategy_id).mode == "shadow":
        return Decision(approved_quantity=0, skip_reason="shadow", failed_checks=("shadow",),
                        sizer="held_shares", sized_quantity=0)

    held = context.shares_held(request.strategy_id, request.signal.ticker)
    broker = context.broker_shares(request.signal.ticker)
    quantity = min(held, broker)
    if quantity == 0:
        return Decision(approved_quantity=0, skip_reason="nothing_to_sell", failed_checks=("nothing_to_sell",),
                        sizer="held_shares", sized_quantity=held)
    return Decision(approved_quantity=quantity, skip_reason=None, failed_checks=(),
                    sizer="held_shares", sized_quantity=held)
