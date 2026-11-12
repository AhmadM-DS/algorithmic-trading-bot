"""
sweep.py
Once per cycle: close day positions near the close, leftovers from an earlier day and closes that haven't finished
"""

#Standard Library
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

#Third Party Libraries
import pyodbc

#Local Imports
from config.constants import CLOSING_ALERT_MINUTES, END_OF_DAY_CLOSE_MINUTES
from data.market_calendar import session_times
from execution.broker import BrokerUnavailable, OrderRejected
from exits.close import ExitResult, close_position
from logger import trades_log
from notifications import send_critical
from storage.exits import get_closing_positions, get_open_buys, get_open_position, get_positions_by_holding_type

DONE_TRYING = ("sent", "nothing_to_sell")

@dataclass(frozen=True)
class ExitReport:
    """What one sweep did

    status: "done", "market_closed" (nothing runs outside regular hours), "database_down" or "broker_unavailable"
    (no positions read, or no share counts, so nothing was sold).
    """
    status: str
    results: tuple = ()
    cancelled_buys: tuple = ()

def close_time(session_close: datetime, holding_type: str) -> datetime | None:
    """Return when a holding type's end-of-day close starts: END_OF_DAY_CLOSE_MINUTES before that day's close

    Parameters:
        session_close (datetime): Today's close from the trading calendar (early closes included)
        holding_type (str): e.g. "day"

    Returns:
        The start time, or None for a holding type that's never closed at the end of the day (swing)
    """
    minutes = END_OF_DAY_CLOSE_MINUTES.get(holding_type)
    return None if minutes is None else session_close - timedelta(minutes=minutes)

def _naive_utc(moment: datetime) -> datetime:
    """Return a timezone-aware time as naive UTC, as the database stores it"""
    return moment.astimezone(timezone.utc).replace(tzinfo=None)

def _positions_to_close(conn, watch, due_types: list, session_open: datetime) -> list:
    """Return [(position, exit_reason, is_leftover)] in order: earlier-day leftovers, due day positions, the rest"""
    plan, seen = [], set()

    def add(position, exit_reason, leftover=False):
        if position["position_id"] not in seen:
            seen.add(position["position_id"])
            plan.append((position, watch.reason(position["position_id"]) or exit_reason, leftover))

    end_of_day = get_positions_by_holding_type(conn, list(END_OF_DAY_CLOSE_MINUTES))
    for position in end_of_day:
        if position["opened_at"] < session_open:
            add(position, "end_of_day", leftover=True)
    for position in end_of_day:
        if position["holding_type"] in due_types:
            add(position, "end_of_day")
    for position in get_closing_positions(conn):
        add(position, position["last_exit_reason"])
    for position_id in list(watch.closing):
        if position_id not in seen:
            position = get_open_position(conn, position_id)
            if position is None:
                watch.forget(position_id)
            else:
                add(position, watch.reason(position_id))
    return plan

def _cancel_open_buys(broker, buys: list) -> list:
    """Cancel day buys still waiting at the close, so none can fill after the sweep; return their client_order_ids"""
    cancelled = []
    for buy in buys:
        if buy["alpaca_order_id"] is None:
            trades_log.warning(f"Can't cancel {buy['client_order_id']} at the close yet: it's {buy['status']} with "
                               "no Alpaca ID (settle_stuck_orders looks it up)")
            continue
        try:
            broker.cancel_order(buy["alpaca_order_id"])
        except OrderRejected as error:
            trades_log.info(f"Cancel of {buy['client_order_id']} at the close refused ({error}); it's already done")
            continue
        except BrokerUnavailable as error:
            trades_log.warning(f"Cancel of {buy['client_order_id']} at the close failed: {error}")
            continue
        trades_log.warning(f"Cancelled {buy['strategy']} buy of {buy['ticker']} ({buy['client_order_id']}) at the "
                           f"end-of-day close: it was still {buy['status']}")
        cancelled.append(buy["client_order_id"])
    return cancelled

def _alert_if_stuck(watch, position: dict, exit_reason: str, result: ExitResult, now: datetime):
    """Send one critical alert when a close has run CLOSING_ALERT_MINUTES without its sell going out"""
    if result.status in DONE_TRYING or not watch.stuck(position["position_id"], now, CLOSING_ALERT_MINUTES):
        return
    send_critical(f"Position {position['position_id']} ({position['strategy']} {position['ticker']}) is still open "
                  f"{CLOSING_ALERT_MINUTES} minutes after the bot started closing it ({exit_reason}): "
                  f"{result.status} {result.detail}. Its stop may already be cancelled; the bot keeps trying "
                  "every minute.")

def run_exits(conn, broker, calendar: dict, now: datetime, watch, prices: dict | None = None,
              sleep=time.sleep) -> ExitReport:
    """Close every position that has to close now; safe to call every minute

    Runs only in regular hours. Closes, in this order: day positions opened on an earlier trading day (one
    critical alert each), day positions once END_OF_DAY_CLOSE_MINUTES before the close is reached (after
    cancelling day buys still waiting), and positions whose close was started but hasn't finished. Alpaca's
    share counts are read once and lowered by each sell, so two positions in one ticker can't oversell.

    Parameters:
        conn (Connection): An open database connection
        broker (AlpacaBroker): The broker to cancel and sell through
        calendar (dict): Trading days from market_calendar.get_calendar
        now (datetime): The real time now, timezone-aware
        watch (ExitWatch): What the exits remember between cycles
        prices (dict | None): {ticker: latest price}, saved as each sell's request_price
        sleep (callable): How to wait; tests pass one that doesn't

    Returns:
        An ExitReport
    """
    session_open, session_close = session_times(calendar, now)
    if session_open is None or not session_open <= now < session_close:
        return ExitReport("market_closed")
    stamp = _naive_utc(now)
    due_types = [holding_type for holding_type in END_OF_DAY_CLOSE_MINUTES
                 if now >= close_time(session_close, holding_type)]

    try:
        plan = _positions_to_close(conn, watch, due_types, _naive_utc(session_open))
        buys = get_open_buys(conn, due_types)
    except pyodbc.Error as error:
        trades_log.error(f"Exits can't run: the database didn't answer: {error}")
        if due_types and watch.first_time(("database_down", stamp.date())):
            send_critical(f"End-of-day close can't run: the database didn't answer ({error}). Open day positions "
                          "may stay overnight; the bot retries every minute.")
        return ExitReport("database_down")

    cancelled = tuple(_cancel_open_buys(broker, buys))
    if not plan:
        return ExitReport("done", cancelled_buys=cancelled)
    for position, exit_reason, _ in plan:
        watch.start(position["position_id"], exit_reason, stamp)

    try:
        shares = broker.get_positions()
    except BrokerUnavailable as error:
        trades_log.warning(f"Exits wait: no share counts from Alpaca: {error}")
        for position, exit_reason, _ in plan:
            failed = ExitResult(position["position_id"], "broker_unavailable", detail=str(error))
            _alert_if_stuck(watch, position, exit_reason, failed, stamp)
        return ExitReport("broker_unavailable", cancelled_buys=cancelled)

    results = []
    for position, exit_reason, leftover in plan:
        if leftover and watch.first_time(("leftover", position["position_id"])):
            send_critical(f"Day position {position['position_id']} ({position['strategy']} {position['ticker']}, "
                          f"opened {position['opened_at']:%Y-%m-%d %H:%M} UTC) was still open at today's open. "
                          "Closing it now.")
        try:
            result = close_position(position, exit_reason, conn, broker, shares=shares,
                                    price=(prices or {}).get(position["ticker"]), now=stamp, watch=watch, sleep=sleep)
        except pyodbc.Error as error:
            trades_log.error(f"Exits stopped at position {position['position_id']}: the database failed: {error}")
            results.append(ExitResult(position["position_id"], "database_down", detail=str(error)))
            break
        results.append(result)
        _alert_if_stuck(watch, position, exit_reason, result, stamp)
    return ExitReport("done", tuple(results), cancelled)
