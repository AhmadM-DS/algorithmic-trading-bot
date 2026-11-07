"""
records.py
The only risk code that writes: the bot_events rows that lock halts (with their alerts) and saved risk decisions
"""

#Standard Library
import math

#Local Imports
from logger import trades_log
from notifications import send_critical, send_trades
from risk.context import RiskContext
from risk.decisions import Decision, RiskRequest
from storage.events import insert_bot_event
from storage.risk import insert_risk_decision, insert_risk_decision_parameter

def record_risk_events(conn, context: RiskContext, alert_channels: dict = None) -> int:
    """Save a bot_events row for each state that started this cycle, then send its alert once

    The row is what locks a halt and stops the alert repeating next cycle, so the alerts go out only after
    the commit.

    Parameters:
        conn (Connection): An open database connection; this function commits
        context (RiskContext): This cycle's snapshot from build_context
        alert_channels (dict): {"critical": send, "trades": send}; Discord if None

    Returns:
        How many events were saved
    """
    if not context.events:
        return 0
    channels = alert_channels or {"critical": send_critical, "trades": send_trades}
    for event in context.events:
        insert_bot_event(conn, event.event_type, event.message, event.strategy_id)
    conn.commit()
    for event in context.events:
        log = trades_log.warning if event.channel == "critical" else trades_log.info
        log(event.message)
        channels[event.channel](event.message)
    return len(context.events)

def save_risk_decision(conn, signal_id: int, request: RiskRequest, decision: Decision, context: RiskContext) -> int:
    """Save what risk knew when it decided a signal, with every parameter it used

    Called once the signal is saved. Doesn't commit, so the signal and its decision commit together.

    Parameters:
        conn (Connection): An open database connection
        signal_id (int): The saved signal
        request (RiskRequest): What was asked
        decision (Decision): What risk answered
        context (RiskContext): The snapshot it decided from

    Returns:
        The new risk_decision_id
    """
    state = context.strategy(request.strategy_id)
    ticker = request.signal.ticker
    risk_decision_id = insert_risk_decision(
        conn, signal_id, sizer=decision.sizer, sized_quantity=decision.sized_quantity, equity=context.equity,
        buying_power=context.buying_power, trading_budget=state.trading_budget,
        account_exposure=context.exposure(), strategy_exposure=context.exposure(strategy_id=request.strategy_id),
        ticker_exposure=context.exposure(ticker=ticker), open_positions=context.position_count(),
        shares_held=context.shares_held(request.strategy_id, ticker), broker_shares=context.broker_shares(ticker),
        strategy_daily_pnl=state.pnl_today(request.signal.holding_type), strategy_drawdown=state.drawdown,
        account_daily_change=context.account_daily_change, start_equity=context.start_equity)
    for parameter in decision.parameters:
        insert_risk_decision_parameter(
            conn, risk_decision_id, name=parameter.name, provider=parameter.provider,
            proposed=None if math.isnan(parameter.proposed) else parameter.proposed, used=parameter.used,
            clamped="clamp" in parameter.limited_by, rate_limited="rate_limit" in parameter.limited_by,
            fell_back="fallback" in parameter.limited_by)
    return risk_decision_id
