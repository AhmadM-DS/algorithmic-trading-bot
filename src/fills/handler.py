"""
handler.py
Apply one TradeUpdate to the database: the order's status, its trades row and the position it opens or closes
"""

#Standard Library
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

#Local Imports
from config.constants import UNKNOWN_ORDER_WAIT_SECONDS
from data.market_calendar import NEW_YORK
from logger import trades_log
from storage.connections import is_duplicate_error
from storage.fills import (add_to_position, close_position, find_order_row, get_entry_defaults,
                           get_open_positions_for_ticker, get_order_position, get_position, get_position_totals,
                           get_strategy_id, insert_position, insert_trade, save_broker_event, set_legs_position,
                           set_order_position, set_order_price_from_trades, trade_exists, update_order_from_broker)
from storage.orders import insert_order, save_rejection
from storage.watchlist import get_or_create_ticker

MANUAL = "manual"
LATE_REJECTION = "Rejected by Alpaca after it was accepted (the stream gives no reason)"

@dataclass
class HandleResult:
    """What handling one update did, plus the alerts to send once it's committed

    outcome is one of: "handled", "duplicate" (fill already saved), "waiting" (no order row yet; retried),
    "no_order" (a non-fill event for an order the bot doesn't have), "unresolved" (needs a person; alerted),
    "failed" (an error; rolled back and retried).
    alerts is a list of (channel, message), channel "critical" or "trades".
    """
    outcome: str
    alerts: list = field(default_factory=list)

def _new_york_date(utc_time: datetime):
    """Return the New York date of a naive UTC time"""
    return utc_time.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(NEW_YORK)).date()

def _record_manual_order(conn, update) -> dict:
    """Save an order the bot didn't place under the manual strategy and return its row"""
    insert_order(conn, client_order_id=update.client_order_id or f"manual-{update.alpaca_order_id}",
                 alpaca_order_id=update.alpaca_order_id, side=update.side,
                 quantity=update.requested_quantity or update.fill_quantity,
                 order_type=update.order_type or "unknown", time_in_force=update.time_in_force or "unknown",
                 submitted_at=update.event_at, status=update.status, strategy_id=get_strategy_id(conn, MANUAL),
                 ticker_id=get_or_create_ticker(conn, update.ticker, _new_york_date(update.event_at)),
                 exit_reason=MANUAL if update.side == "sell" else None)
    return find_order_row(conn, update.alpaca_order_id, None)

def _link_leg(conn, order: dict):
    """Copy the buy's position onto a bracket leg that doesn't have one yet (the buy can fill first)"""
    if order["parent_order_id"] is not None and order["position_id"] is None:
        position_id = get_order_position(conn, order["parent_order_id"])
        if position_id is not None:
            set_order_position(conn, order["order_id"], position_id)
            order["position_id"] = position_id

def _record_buy_fill(conn, order: dict, update):
    """Open the order's position on its first fill or add to it on later ones, then save the trade"""
    position_id = order["position_id"]
    if position_id is None:
        time_frame, holding_type = get_entry_defaults(conn, order["strategy_id"], order["signal_id"])
        position_id = insert_position(conn, strategy_id=order["strategy_id"], ticker_id=order["ticker_id"],
                                      signal_id=order["signal_id"], time_frame=time_frame,
                                      holding_type=holding_type, opened_at=update.event_at,
                                      quantity=update.fill_quantity, price=update.fill_price)
        set_order_position(conn, order["order_id"], position_id)
        set_legs_position(conn, order["order_id"], position_id)
    else:
        add_to_position(conn, position_id, update.fill_quantity, update.fill_price)
    insert_trade(conn, fill_id=update.execution_id, side="buy", quantity=update.fill_quantity,
                 filled_at=update.event_at, fill_price=update.fill_price,
                 time_frame=get_position(conn, position_id)["time_frame"], exit_reason=None,
                 position_id=position_id, order_id=order["order_id"])
    trades_log.info(f"Fill: buy {update.fill_quantity} {update.ticker} @ {update.fill_price} "
                    f"({order['strategy']}, position {position_id})")
    return "handled"

def _position_for_manual_sell(conn, order: dict, update, alerts: list) -> int | None:
    """Pick the position a manual sell takes shares from: a manual one first, else the oldest open one"""
    positions = get_open_positions_for_ticker(conn, order["ticker_id"])
    if not positions:
        alerts.append(("critical", f"Manual sell of {update.fill_quantity} {update.ticker} "
                                   f"({update.alpaca_order_id}), but no open position holds {update.ticker}. "
                                   "Not recorded as a trade; fix by hand."))
        return None
    first = positions[0]
    if first["shares_held"] < update.fill_quantity:
        alerts.append(("critical", f"Manual sell of {update.fill_quantity} {update.ticker} "
                                   f"({update.alpaca_order_id}) is more than position {first['position_id']} "
                                   f"({first['strategy']}, {first['shares_held']} shares) holds, so it spans "
                                   "positions. Not recorded as a trade; fix by hand. Buys stay blocked until the "
                                   "share counts match (A2)."))
        return None
    return first["position_id"]

def _record_sell_fill(conn, order: dict, update, alerts: list):
    """Save the trade against the position it sells from and close the position when no shares are left"""
    position_id = order["position_id"]
    if position_id is None and order["strategy"] == MANUAL:
        position_id = _position_for_manual_sell(conn, order, update, alerts)
        if position_id is None:
            return "unresolved"
        set_order_position(conn, order["order_id"], position_id)
    if position_id is None:
        alerts.append(("critical", f"Sell fill for {order['client_order_id']} ({update.fill_quantity} "
                                   f"{update.ticker}) has no position to close. Not recorded as a trade; "
                                   "fix by hand."))
        return "unresolved"
    exit_reason = order["exit_reason"]
    if exit_reason is None:
        alerts.append(("critical", f"Sell fill for {order['client_order_id']} ({update.fill_quantity} "
                                   f"{update.ticker}) has no exit_reason on its order. Not recorded as a trade; "
                                   "fix by hand."))
        return "unresolved"

    insert_trade(conn, fill_id=update.execution_id, side="sell", quantity=update.fill_quantity,
                 filled_at=update.event_at, fill_price=update.fill_price,
                 time_frame=get_position(conn, position_id)["time_frame"], exit_reason=exit_reason,
                 position_id=position_id, order_id=order["order_id"])
    totals = get_position_totals(conn, position_id)
    trades_log.info(f"Fill: sell {update.fill_quantity} {update.ticker} @ {update.fill_price} "
                    f"({order['strategy']}, {exit_reason}, position {position_id}, {totals['shares_held']} left)")
    if totals["shares_held"] == 0:
        realized_pnl = totals["sold"] - totals["bought"]
        close_position(conn, position_id, update.event_at, exit_reason, realized_pnl)
        trades_log.info(f"Closed position {position_id} ({update.ticker}, {exit_reason}): {realized_pnl:+.2f}")
    elif totals["shares_held"] < 0:
        alerts.append(("critical", f"Position {position_id} ({update.ticker}) now shows "
                                   f"{totals['shares_held']} shares after selling {update.fill_quantity}. "
                                   "More was sold than bought; check it by hand."))
    return "handled"

def _status_alerts(conn, order: dict, update, alerts: list):
    """Add alerts for a late rejection or a bracket leg that expired while its position is still open"""
    if update.event_type == "rejected":
        save_rejection(conn, order["order_id"], LATE_REJECTION)
        alerts.append(("critical", f"Order {order['client_order_id']} ({update.side} {update.ticker}) was "
                                   "rejected by Alpaca after it was accepted."))
    if (update.status == "expired" and order["parent_order_id"] is not None and order["position_id"] is not None
            and get_position(conn, order["position_id"])["status"] == "open"):
        alerts.append(("critical", f"The {order['order_type']} leg of position {order['position_id']} "
                                   f"({update.ticker}) expired while the position is still open: it has no "
                                   "stop at Alpaca now."))

def handle_update(conn, update, now: datetime, wait_seconds: int = UNKNOWN_ORDER_WAIT_SECONDS) -> HandleResult:
    """Apply one TradeUpdate to orders, trades and positions

    A fill whose order row doesn't exist yet waits (E1 may still be saving it); after wait_seconds it's
    treated as a trade the bot didn't make and recorded under the manual strategy. Doesn't commit and
    doesn't send alerts: the caller commits, then sends the result's alerts.

    Parameters:
        conn (Connection): An open database connection
        update (TradeUpdate): What Alpaca reported
        now (datetime): The UTC time now, naive
        wait_seconds (int): How long a fill may wait for its order row

    Returns:
        A HandleResult with the outcome and any alerts

    Raises:
        pyodbc.Error if a write fails (the caller rolls back)
    """
    alerts = []
    order = find_order_row(conn, update.alpaca_order_id, update.client_order_id)
    if order is None:
        if not update.is_fill:
            return HandleResult("no_order")
        if now - update.event_at < timedelta(seconds=wait_seconds):
            return HandleResult("waiting")
        order = _record_manual_order(conn, update)
        alerts.append(("trades", f"Manual trade recorded: {update.side} {update.fill_quantity} {update.ticker} "
                                 f"@ {update.fill_price} ({update.alpaca_order_id})"))

    update_order_from_broker(conn, order["order_id"], update.alpaca_order_id, update.status,
                             update.filled_quantity, update.filled_price)
    _link_leg(conn, order)

    outcome = "handled"
    if update.is_fill:
        if trade_exists(conn, update.execution_id):
            outcome = "duplicate"
        elif update.side == "buy":
            outcome = _record_buy_fill(conn, order, update)
        else:
            outcome = _record_sell_fill(conn, order, update, alerts)
        if outcome == "handled" and update.filled_price is None:
            set_order_price_from_trades(conn, order["order_id"])
    _status_alerts(conn, order, update, alerts)
    return HandleResult(outcome, alerts)

def process_update(conn, update, now: datetime, save_raw: bool = True,
                   wait_seconds: int = UNKNOWN_ORDER_WAIT_SECONDS) -> HandleResult:
    """Save an update raw, then handle it in its own transaction

    The raw broker_events row is committed first, so a failure while handling can't lose the event;
    a failed handling is rolled back and the retry pass tries again later. Never raises for a handling
    error, so the stream keeps listening.

    Parameters:
        conn (Connection): An open database connection; this function commits
        update (TradeUpdate): What Alpaca reported
        now (datetime): The UTC time now, naive
        save_raw (bool): False when the event is already in broker_events (the retry pass)
        wait_seconds (int): How long a fill may wait for its order row

    Returns:
        A HandleResult; outcome "failed" (with a critical alert) if handling raised

    Raises:
        pyodbc.Error if the raw row itself can't be saved (the catch-up recovers the event later)
    """
    if save_raw:
        save_broker_event(conn, event_type=update.event_type, alpaca_order_id=update.alpaca_order_id,
                          client_order_id=update.client_order_id, execution_id=update.execution_id,
                          ticker=update.ticker, event_at=update.event_at, raw_json=update.raw_json)
        conn.commit()
    try:
        result = handle_update(conn, update, now, wait_seconds)
        conn.commit()
    except Exception as error:
        conn.rollback()
        if update.is_fill and is_duplicate_error(error):
            return HandleResult("duplicate")
        trades_log.error(f"Couldn't handle {update.event_type} for {update.alpaca_order_id} ({update.ticker}): "
                         f"{error}")
        return HandleResult("failed", [("critical", f"Couldn't handle a {update.event_type} for {update.ticker} "
                                                    f"({update.alpaca_order_id}): {error}. Saved raw; "
                                                    "retried every minute.")])
    if result.outcome not in ("handled", "duplicate"):
        trades_log.info(f"{update.event_type} for {update.alpaca_order_id} ({update.ticker}): {result.outcome}")
    return result
