"""
catch_up.py
Find what the stream missed (fills and order status changes) and retry fills whose handling didn't finish
"""

#Standard Library
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

#Local Imports
from config.constants import CATCH_UP_MARGIN_SECONDS, UNKNOWN_ORDER_WAIT_SECONDS
from data.market_calendar import NEW_YORK
from fills.events import UNREADABLE_ERRORS, from_activity, from_broker_order, from_saved
from fills.handler import process_update
from logger import trades_log
from storage.fills import fill_seen, get_last_event_time, get_open_orders, get_unhandled_fills, trade_exists

@dataclass
class CatchUpResult:
    """What one catch-up found: new fills, order status changes, retried fills, and the alerts they raised"""
    fills: int = 0
    status_changes: int = 0
    retried: int = 0
    alerts: list = field(default_factory=list)

    @property
    def found_anything(self) -> bool:
        return bool(self.fills or self.status_changes or self.retried)

def catch_up_start(conn, now: datetime, margin_seconds: int = CATCH_UP_MARGIN_SECONDS) -> datetime:
    """Return the time the catch-up asks Alpaca for fills from

    The newest saved event's time minus a safety margin, or the start of today (New York) on the first run.

    Parameters:
        conn (Connection): An open database connection
        now (datetime): The UTC time now, naive
        margin_seconds (int): How far before the newest saved event to start

    Returns:
        A naive UTC datetime
    """
    last = get_last_event_time(conn)
    if last is not None:
        return last - timedelta(seconds=margin_seconds)
    today = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(NEW_YORK)).date()
    return datetime.combine(today, time(0), ZoneInfo(NEW_YORK)).astimezone(timezone.utc).replace(tzinfo=None)

def retry_unhandled(conn, now: datetime, wait_seconds: int = UNKNOWN_ORDER_WAIT_SECONDS) -> list:
    """Handle again every saved fill that has no trades row yet

    A saved message that can't be read (alerted when it arrived) is skipped; the end-of-day audit records its fill
    from Alpaca's activities.

    Parameters:
        conn (Connection): An open database connection; commits after each fill
        now (datetime): The UTC time now, naive
        wait_seconds (int): How long a fill may wait for its order row

    Returns:
        The HandleResult of each retried fill
    """
    results = []
    for row in get_unhandled_fills(conn):
        try:
            update = from_saved(row["event_type"], row["raw_json"])
        except UNREADABLE_ERRORS as error:
            trades_log.warning(f"Skipped unreadable saved fill {row['broker_event_id']}: {type(error).__name__}: "
                               f"{error}")
            continue
        results.append(process_update(conn, update, now, save_raw=False, wait_seconds=wait_seconds))
    return results

def _activity_order(activity) -> str:
    """Sort key: the activity's transaction time as Alpaca wrote it; one that can't be read sorts first"""
    return str(activity.get("transaction_time") or "") if isinstance(activity, dict) else ""

def catch_up(conn, broker, now: datetime, wait_seconds: int = UNKNOWN_ORDER_WAIT_SECONDS) -> CatchUpResult:
    """Record what the stream missed, then retry unfinished fills

    1. Fills: Alpaca's FILL activities since catch_up_start; each one not saved yet goes through the same
       code as a stream fill (saved raw as "catch_up_fill", then handled). One that can't be read is logged and
       skipped; the end-of-day audit saves it as a failure and alerts it.
    2. Statuses: every order not in a final status is looked up; a changed status or filled quantity is
       saved raw as "catch_up_status" and handled (this finds legs canceled or expired while not listening).
    3. Retry: saved fills with no trades row yet are handled again.

    Parameters:
        conn (Connection): An open database connection; commits as it goes
        broker (AlpacaBroker): The broker to ask
        now (datetime): The UTC time now, naive
        wait_seconds (int): How long a fill may wait for its order row

    Returns:
        A CatchUpResult with counts and alerts

    Raises:
        BrokerUnavailable if Alpaca can't be asked (the next catch-up tries again)
    """
    result = CatchUpResult()
    activities = broker.get_fill_activities(catch_up_start(conn, now))
    for activity in sorted(activities, key=_activity_order):
        try:
            update = from_activity(activity)
        except UNREADABLE_ERRORS as error:
            trades_log.warning(f"Catch-up skipped an activity it can't read ({type(error).__name__}: {error}); the "
                               f"end-of-day audit records it: {activity!r}")
            continue
        if fill_seen(conn, update.execution_id) or trade_exists(conn, update.execution_id):
            continue
        handled = process_update(conn, update, now, wait_seconds=wait_seconds)
        result.fills += 1
        result.alerts += handled.alerts

    for row in get_open_orders(conn):
        found = broker.get_order(row["alpaca_order_id"])
        if found is None or (found.status, found.filled_quantity) == (row["status"], row["filled_quantity"]):
            continue
        handled = process_update(conn, from_broker_order(found, row["ticker"], now), now, wait_seconds=wait_seconds)
        result.status_changes += 1
        result.alerts += handled.alerts

    for handled in retry_unhandled(conn, now, wait_seconds):
        if handled.outcome != "waiting":
            result.retried += 1
        result.alerts += handled.alerts

    if result.found_anything:
        trades_log.info(f"Catch-up: {result.fills} missed fills, {result.status_changes} status changes, "
                        f"{result.retried} fills retried")
    return result
