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
from risk.context import RiskContext
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
    """Block a buy when the whole account already holds MAX_OPEN_POSITIONS positions

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "max_positions" if the account is full, None otherwise
    """
    open_count = len(context.positions())
    return "max_positions" if open_count >= MAX_OPEN_POSITIONS else None

def check_positions_per_ticker(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a buy when this strategy already holds MAX_POSITIONS_PER_TICKER positions in the ticker

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "max_positions_per_ticker" if this strategy can't stack more of the ticker, None otherwise
    """
    open_count = len(context.positions(request.strategy_id, request.signal.ticker))
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

def check_cooldown(request: RiskRequest, context: RiskContext, quantity: int) -> str | None:
    """Block a buy while this strategy is cooling down after its last exit from the ticker

    The wait is a number of the strategy's candles, set per exit reason by the cooldown_<reason> parameters.
    Exit reasons with no parameter (end_of_day, kill_switch, manual, liquidation) have no cooldown.

    Parameters:
        request (RiskRequest): The buy being checked
        context (RiskContext): This cycle's snapshot
        quantity (int): The sizer's share count

    Returns:
        "cooldown" if the wait isn't over yet, None otherwise
    """
    last = context.last_exit(request.strategy_id, request.signal.ticker)
    if last is None:
        return None

    name = f"cooldown_{last.exit_reason}"
    if name not in RISK_PARAMETERS:
        return None

    candles = get_parameter(name, request.strategy_id, context).used
    wait = timedelta(minutes=candles * to_minutes(request.signal.time_frame))
    return "cooldown" if context.as_of < last.closed_at + wait else None
