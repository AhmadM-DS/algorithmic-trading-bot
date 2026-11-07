"""
snapshot.py
Build the RiskContext once per cycle (startup is the first cycle) from Alpaca and the database
"""

#Standard Library
from dataclasses import replace
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

#Third Party Libraries
import pyodbc

#Local Imports
from config.constants import DAILY_HALT_LIMITS, KILL_SWITCH_FRACTION, MAX_LEVERAGE, RISK_EQUITY_CAP
from data.market_calendar import NEW_YORK
from execution.broker import BrokerError
from risk.context import BrokerPosition, OpenPosition, PendingBuy, RecentExit, RiskContext, RiskEvent, StrategyState
from risk.parameters import get_parameter
from storage.orders import get_pending_buys
from storage.risk import (get_daily_pnl, get_events_since, get_events_since_budget_set, get_exits_since,
                          get_latest_events, get_open_positions, get_pnl_since_budget, get_previous_parameters,
                          get_strategy_rows)

KILL_SWITCH = "kill_switch"
DRAWDOWN_LIMIT = "drawdown_limit"
SCALE_DOWN_STARTED = "scale_down_started"
SCALE_DOWN_STOPPED = "scale_down_stopped"
BUDGET_FULL = "budget_full"
BUDGET_ROOM = "budget_room"

class RiskStateUnavailable(Exception):
    """Alpaca or the database didn't answer, so there's no snapshot and no buys this cycle"""

def daily_halt_event(holding_type: str) -> str:
    """Return the bot_events type that locks one holding type's daily halt, e.g. "daily_halt_day"

    Parameters:
        holding_type (str): "day" or "swing"

    Returns:
        The event_type
    """
    return f"daily_halt_{holding_type}"

def start_of_day(now: datetime) -> datetime:
    """Return midnight New York time today as naive UTC, the start of the trading day

    Parameters:
        now (datetime): A timezone-aware time

    Returns:
        A naive UTC datetime
    """
    today = now.astimezone(ZoneInfo(NEW_YORK)).date()
    return datetime.combine(today, time(0), ZoneInfo(NEW_YORK)).astimezone(timezone.utc).replace(tzinfo=None)

def _capped(value: float, cap: float | None) -> float:
    """Return value limited to the equity cap; None means no cap"""
    return value if cap is None else min(value, cap)

def _utc(value: datetime) -> datetime:
    """Return a naive UTC time from the database as timezone-aware"""
    return value.replace(tzinfo=timezone.utc)

def _effective_budget(row: dict, pnl: dict, scale: float) -> float:
    """Return the budget risk may use: losses since the budget was set shrink it, profits don't grow it,
    and a live budget is scaled down when the account can't cover every live budget"""
    budget = float(row["budget"])
    after_losses = budget + min(0.0, float(pnl["total"])) if pnl else budget
    share = budget * scale if row["mode"] == "live" else budget
    return max(0.0, min(after_losses, share))

def _drawdown(pnl: dict) -> float:
    """Return how far the realized P/L since the budget was set is below its peak; the peak is never below 0"""
    if not pnl:
        return 0.0
    return max(0.0, float(pnl["peak"])) - float(pnl["total"])

def _base_context(conn, broker, now: datetime, trading_mode: str) -> RiskContext:
    """Read everything the snapshot holds before any halt is worked out"""
    account = broker.get_account()
    held = broker.get_positions()
    cap = RISK_EQUITY_CAP[trading_mode]
    equity = _capped(float(account.equity), cap)
    day_start = start_of_day(now)
    trade_date = now.astimezone(ZoneInfo(NEW_YORK)).date()

    rows = get_strategy_rows(conn)
    live_budgets = sum(float(row["budget"]) for row in rows if row["mode"] == "live")
    scale = min(1.0, equity * MAX_LEVERAGE / live_budgets) if live_budgets > 0 else 1.0
    pnl_since = get_pnl_since_budget(conn)
    daily = get_daily_pnl(conn, trade_date)

    strategies = tuple(
        StrategyState(strategy_id=row["strategy_id"], mode=row["mode"],
                      effective_budget=_effective_budget(row, pnl_since.get(row["strategy_id"]), scale),
                      name=row["strategy"], budget=float(row["budget"]),
                      daily_pnl={holding_type: float(pnl) for (strategy_id, holding_type), pnl in daily.items()
                                 if strategy_id == row["strategy_id"]},
                      drawdown=_drawdown(pnl_since.get(row["strategy_id"])))
        for row in rows)
    positions = tuple(
        OpenPosition(position_id=row["position_id"], strategy_id=row["strategy_id"], ticker=row["ticker"],
                     holding_type=row["holding_type"], shares_held=row["shares_held"],
                     avg_entry_price=float(row["avg_entry_price"]))
        for row in get_open_positions(conn))
    exits = tuple(
        RecentExit(strategy_id=row["strategy_id"], ticker=row["ticker"], exit_reason=row["exit_reason"],
                   closed_at=_utc(row["closed_at"]))
        for row in get_exits_since(conn, day_start))
    pending = tuple(
        PendingBuy(strategy_id=row["strategy_id"], ticker=row["ticker"], quantity=row["unfilled"],
                   price=float(row["request_price"] or 0), has_position=row["position_id"] is not None)
        for row in get_pending_buys(conn))

    return RiskContext(as_of=now, equity=equity, buying_power=float(account.buying_power), strategies=strategies,
                       open_positions=positions, recent_exits=exits,
                       broker_positions=tuple(BrokerPosition(ticker, shares) for ticker, shares in held.items()),
                       account_daily_change=float(account.equity - account.last_equity),
                       start_equity=_capped(float(account.last_equity), cap), scale_down=scale,
                       previous_parameters=get_previous_parameters(conn, day_start), pending_buys=pending)

def _kill_switch(context: RiskContext, locked: bool, events: list) -> bool:
    """Return whether the kill switch is on; add an event the first time it trips today"""
    loss = -context.account_daily_change
    tripped = context.start_equity > 0 and loss >= KILL_SWITCH_FRACTION * context.start_equity
    if tripped and not locked:
        events.append(RiskEvent(KILL_SWITCH, None, "critical",
                                f"Kill switch: the account is down ${loss:.2f} today, "
                                f"{loss / context.start_equity:.1%} of ${context.start_equity:.2f} "
                                f"(limit {KILL_SWITCH_FRACTION:.0%}). No new buys until tomorrow; open positions "
                                "keep their stops."))
    return locked or tripped

def _scale_down_events(context: RiskContext, latest: str | None, events: list):
    """Add an event when the live budgets start or stop being scaled down to the account"""
    if context.scale_down < 1.0 and latest != SCALE_DOWN_STARTED:
        events.append(RiskEvent(SCALE_DOWN_STARTED, None, "critical",
                                f"The live budgets add up to more than the account (${context.equity:.2f} x "
                                f"{MAX_LEVERAGE}); every live budget is scaled to {context.scale_down:.0%}."))
    elif context.scale_down >= 1.0 and latest == SCALE_DOWN_STARTED:
        events.append(RiskEvent(SCALE_DOWN_STOPPED, None, "trades",
                                "The account covers every live budget again; budgets are back to full size."))

def _daily_halts(state: StrategyState, locked: set, events: list) -> frozenset:
    """Return the holding types this strategy is halted for today; add an event for each new halt"""
    halted = set()
    budget = state.trading_budget
    for holding_type, limits in DAILY_HALT_LIMITS.items():
        pnl = state.pnl_today(holding_type)
        tripped = budget > 0 and (pnl <= -limits["loss"] * budget or pnl >= limits["profit"] * budget)
        is_locked = (daily_halt_event(holding_type), state.strategy_id) in locked
        if tripped and not is_locked:
            events.append(RiskEvent(daily_halt_event(holding_type), state.strategy_id, "trades",
                                    f"Daily halt: {state.name} {holding_type} trades are {pnl:+.2f} today "
                                    f"({pnl / budget:+.1%} of ${budget:.2f}; limits -{limits['loss']:.0%} / "
                                    f"+{limits['profit']:.0%}). No new {holding_type} buys until tomorrow."))
        if tripped or is_locked:
            halted.add(holding_type)
    return frozenset(halted)

def _drawdown_check(state: StrategyState, context: RiskContext, locked: bool, events: list):
    """Return (paused, the drawdown_limit parameter); add an event when the limit is first hit"""
    limit = get_parameter(DRAWDOWN_LIMIT, state.strategy_id, context, context.previous(state.strategy_id, DRAWDOWN_LIMIT))
    tripped = state.drawdown > 0 and state.drawdown >= limit.used * state.budget
    if tripped and not locked:
        events.append(RiskEvent(DRAWDOWN_LIMIT, state.strategy_id, "critical",
                                f"Drawdown limit: {state.name} is ${state.drawdown:.2f} below its peak since its "
                                f"budget was set ({state.drawdown / state.budget:.1%} of ${state.budget:.2f}, limit "
                                f"{limit.used:.0%}). Buys paused until the budget is changed after a review."))
    return locked or tripped, limit

def _budget_events(state: StrategyState, context: RiskContext, latest: str | None, events: list):
    """Add an event when the strategy runs out of room for a full slot, or gets room back"""
    fraction = get_parameter("position_fraction", state.strategy_id, context,
                             context.previous(state.strategy_id, "position_fraction")).used
    slot = state.trading_budget * fraction
    room = state.trading_budget - context.exposure(strategy_id=state.strategy_id)
    if room < slot and latest != BUDGET_FULL:
        events.append(RiskEvent(BUDGET_FULL, state.strategy_id, "trades",
                                f"{state.name}: less than one full slot left (${room:.2f} of ${state.trading_budget:.2f}, "
                                f"a slot is ${slot:.2f}); most buys will be skipped until a position closes."))
    elif room >= slot and latest == BUDGET_FULL:
        events.append(RiskEvent(BUDGET_ROOM, state.strategy_id, "trades",
                                f"{state.name}: room for a full slot again (${room:.2f} of ${state.trading_budget:.2f})."))

def build_context(conn, broker, now: datetime, trading_mode: str) -> RiskContext:
    """Return this cycle's snapshot with every halt worked out, plus the states that started this cycle

    Nothing is kept in memory between cycles: a restart builds the same snapshot. Halts that lock (kill
    switch, daily halt, drawdown limit) stay on while their bot_events row counts, whatever the numbers
    say now; record_risk_events writes the rows for the snapshot's events. Halts apply to live strategies
    with a budget only. Doesn't write anything.

    Parameters:
        conn (Connection): An open database connection
        broker (AlpacaBroker): Asked for the account and its positions (2 calls)
        now (datetime): The time now, timezone-aware
        trading_mode (str): "PAPER" or "LIVE", picks RISK_EQUITY_CAP

    Returns:
        The RiskContext

    Raises:
        RiskStateUnavailable if Alpaca or the database didn't answer
    """
    try:
        base = _base_context(conn, broker, now, trading_mode)
        day_start = start_of_day(now)
        halt_types = (KILL_SWITCH, *(daily_halt_event(holding_type) for holding_type in DAILY_HALT_LIMITS))
        locked_today = get_events_since(conn, halt_types, day_start)
        drawdown_locked = get_events_since_budget_set(conn, DRAWDOWN_LIMIT)
        latest_budget = get_latest_events(conn, (BUDGET_FULL, BUDGET_ROOM))
        latest_scale = get_latest_events(conn, (SCALE_DOWN_STARTED, SCALE_DOWN_STOPPED)).get(None)
    except (BrokerError, pyodbc.Error) as error:
        raise RiskStateUnavailable(f"Couldn't build the risk snapshot: {error}") from error

    events = []
    kill_switch = _kill_switch(base, (KILL_SWITCH, None) in locked_today, events)
    _scale_down_events(base, latest_scale, events)
    strategies = []
    for state in base.strategies:
        if state.mode != "live" or state.budget <= 0:
            strategies.append(state)
            continue
        halted = _daily_halts(state, locked_today, events)
        paused, limit = _drawdown_check(state, base, state.strategy_id in drawdown_locked, events)
        _budget_events(state, base, latest_budget.get(state.strategy_id), events)
        strategies.append(replace(state, halted_holding_types=halted, drawdown_paused=paused, drawdown_limit=limit))
    return replace(base, strategies=tuple(strategies), kill_switch=kill_switch, events=tuple(events))
