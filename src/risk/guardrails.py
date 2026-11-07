"""
guardrails.py
Hard limits every buy must pass; each returns None to pass or a skip code to block
"""
#Standard Library
from datetime import timedelta

#Local Imports
from config.constants import (
    MAX_OPEN_POSITIONS, MAX_POSITIONS_PER_TICKER,
    MAX_LEVERAGE, MAX_ORDER_FRACTION,
    MAX_TICKER_FRACTION, RISK_PARAMETERS)
from risk.context import ParameterValue, RiskContext
from risk.decisions import RiskRequest
from data.time_frames import to_minutes
from risk.parameters import get_parameter

def check_mode(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block buys from strategies that aren't live

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "shadow" or "strategy_off" if the strategy can't trade, None if it's live
    """
    mode = context.strategy(request.strategy_id).mode
    if mode == "shadow":
        return "shadow"
    if mode == "off":
        return "strategy_off"
    return None

def check_kill_switch(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block every buy while the account's kill switch is on today

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "kill_switch" if it's on, None otherwise
    """
    return "kill_switch" if context.kill_switch else None

def check_drawdown(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a strategy's buys once it has fallen its drawdown limit below its peak, until the admin re-sets its budget

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "drawdown_limit" if the strategy is paused, None otherwise
    """
    return "drawdown_limit" if context.strategy(request.strategy_id).drawdown_paused else None

def check_daily_halt(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a strategy's buys of a holding type it hit today's limit for

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "daily_halt" if this strategy is halted for the signal's holding type today, None otherwise
    """
    halted = context.strategy(request.strategy_id).halted_holding_types
    return "daily_halt" if request.signal.holding_type in halted else None

def check_quantity(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a buy the sizer couldn't afford a single share of

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "zero_quantity" if quantity is 0, None otherwise
    """
    return "zero_quantity" if quantity == 0 else None

def check_max_positions(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a buy when the whole account already holds (or has buys on the way for) MAX_OPEN_POSITIONS positions

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "max_positions" if the account is full, None otherwise
    """
    open_count = context.position_count()
    return "max_positions" if open_count >= MAX_OPEN_POSITIONS else None

def check_positions_per_ticker(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a buy when this strategy already holds (or is buying) MAX_POSITIONS_PER_TICKER positions in the ticker

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "max_positions_per_ticker" if this strategy can't stack more of the ticker, None otherwise
    """
    open_count = context.position_count(request.strategy_id, request.signal.ticker)
    return "max_positions_per_ticker" if open_count >= MAX_POSITIONS_PER_TICKER else None

def _order_dollars(request: RiskRequest, quantity: int) -> float:
    """Return what this buy would cost"""
    return quantity * request.price

def check_order_size(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a single order bigger than MAX_ORDER_FRACTION of equity, which means a bug

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "max_order_size" if the order is too big, None otherwise
    """
    limit = context.equity * MAX_ORDER_FRACTION
    return "max_order_size" if _order_dollars(request, quantity) > limit else None

def check_ticker_exposure(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a buy that would put more than MAX_TICKER_FRACTION of equity in one ticker, across all strategies

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "max_per_ticker" if the ticker would be too concentrated, None otherwise
    """
    after = context.exposure(ticker=request.signal.ticker) + _order_dollars(request, quantity)
    return "max_per_ticker" if after > context.equity * MAX_TICKER_FRACTION else None

def check_leverage(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a buy that would put more than equity x MAX_LEVERAGE into open positions

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "max_leverage" if the account would borrow beyond the limit, None otherwise
    """
    after = context.exposure() + _order_dollars(request, quantity)
    return "max_leverage" if after > context.equity * MAX_LEVERAGE else None

def check_buying_power(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a buy that costs more than Alpaca's buying power

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "buying_power" if Alpaca would reject it, None otherwise
    """
    return "buying_power" if _order_dollars(request, quantity) > context.buying_power else None

def check_budget(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a buy that would put this strategy over its trading budget

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "budget_exhausted" if there's no room left in the budget, None otherwise
    """
    budget = context.strategy(request.strategy_id).trading_budget
    after = context.exposure(strategy_id=request.strategy_id) + _order_dollars(request, quantity)
    return "budget_exhausted" if after > budget else None

def cooldown_parameter(request: RiskRequest, context: RiskContext) -> ParameterValue | None:
    """Return the cooldown parameter for this strategy's last exit from the ticker today, if one applies

    Exit reasons with no cooldown_<reason> parameter (end_of_day, kill_switch, manual, liquidation) have no cooldown.

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot

    Returns:
        The ParameterValue (a number of candles), or None if there's no exit or no cooldown for its reason
    """
    last = context.last_exit(request.strategy_id, request.signal.ticker)
    if last is None:
        return None
    name = f"cooldown_{last.exit_reason}"
    if name not in RISK_PARAMETERS:
        return None
    return get_parameter(name, request.strategy_id, context, context.previous(request.strategy_id, name))

def check_cooldown(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a buy while this strategy is cooling down after its last exit from the ticker

    The wait is cooldown_parameter's number of the strategy's candles after the exit.

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "cooldown" if the wait isn't over yet, None otherwise
    """
    parameter = cooldown_parameter(request, context)
    if parameter is None:
        return None
    last = context.last_exit(request.strategy_id, request.signal.ticker)
    wait = timedelta(minutes=parameter.used * to_minutes(request.signal.time_frame))
    return "cooldown" if context.as_of < last.closed_at + wait else None
