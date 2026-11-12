"""
close.py
Close one position: cancel what's still working on it, work out its real shares from Alpaca, then sell them
"""

#Standard Library
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

#Local Imports
from config.constants import CANCEL_WAIT_SECONDS
from execution.broker import BrokerUnavailable, OrderRejected
from execution.orders import OrderRequest, OrderResult, place_order
from logger import trades_log
from notifications import send_critical
from storage.exits import get_position_orders
from storage.fills import FINAL_STATUSES, update_order_from_broker
from storage.orders import DONE_STATUSES

@dataclass(frozen=True)
class ExitResult:
    """What one try at closing a position did

    status: "sent" (the sell is at Alpaca), "rejected" / "unknown" (place_order's), "nothing_to_sell" (its legs
    already sold everything), "order_pending" (a sell is still out, or one of its orders has no answer yet),
    "cancel_pending" (a leg didn't finish cancelling in time), "broker_unavailable" or "short" (Alpaca shows
    fewer than 0 shares; nothing sold).
    """
    position_id: int
    status: str
    quantity: int = 0
    order: OrderResult | None = None
    detail: str = ""

def remaining_shares(orders: list, answers: dict) -> int:
    """Return how many shares a position still holds by its own orders: filled buys minus filled sells

    Alpaca's answer counts for every order in answers, the saved filled_quantity for the rest, so a leg fill the
    fill stream hasn't saved yet can't make one strategy sell another strategy's shares.

    Parameters:
        orders (list): The position's orders from get_position_orders
        answers (dict): {alpaca_order_id: BrokerOrder} just read from Alpaca

    Returns:
        The shares left as an int (0 or below means nothing to sell)
    """
    total = 0
    for order in orders:
        answer = answers.get(order["alpaca_order_id"])
        filled = answer.filled_quantity if answer is not None else order["filled_quantity"]
        total += filled if order["side"] == "buy" else -filled
    return total

def _utc_now() -> datetime:
    """Return the current UTC time without a time zone, as the database stores it"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def _cancel_and_wait(broker, working: list, wait_seconds: int, sleep) -> tuple:
    """Cancel every working order, then read each one every second until all are final or the wait runs out

    Returns:
        ({alpaca_order_id: BrokerOrder}, [alpaca_order_id still not final])
    """
    for order in working:
        try:
            broker.cancel_order(order["alpaca_order_id"])
        except OrderRejected as error:
            trades_log.info(f"Cancel of {order['client_order_id']} refused ({error}); reading its final status")
    answers = {}
    pending = [order["alpaca_order_id"] for order in working]
    for second in range(wait_seconds + 1):
        for alpaca_order_id in pending:
            answer = broker.get_order(alpaca_order_id)
            if answer is not None:
                answers[alpaca_order_id] = answer
        pending = [i for i in pending if i not in answers or answers[i].status not in FINAL_STATUSES]
        if not pending or second == wait_seconds:
            break
        sleep(1)
    return answers, pending

def _save_answers(conn, working: list, answers: dict):
    """Copy Alpaca's answers onto the orders' rows and commit, so a restart sees the cancels"""
    for order in working:
        answer = answers.get(order["alpaca_order_id"])
        if answer is not None:
            update_order_from_broker(conn, order["order_id"], answer.alpaca_order_id, answer.status,
                                     answer.filled_quantity, answer.filled_price)
    conn.commit()

def close_position(position: dict, exit_reason: str, conn, broker, *, shares: dict | None = None, price=None,
                   now: datetime | None = None, watch=None, wait_seconds: int = CANCEL_WAIT_SECONDS,
                   sleep=time.sleep) -> ExitResult:
    """Close one position with a market sell, safely: never two sells for the same shares, never a short

    1. If a sell for it is still out, do nothing (that sell is the close).
    2. Cancel every order still working on it (its bracket legs, or the rest of a partly filled buy) and read
       each from Alpaca every second for up to wait_seconds until it's canceled, filled or expired.
    3. Shares to sell = the smaller of what its own orders say it holds and what Alpaca holds of the ticker.
    4. Send the sell through place_order with the exit_reason, so the fill stream books the right reason.
    Never raises for something Alpaca did; each outcome comes back as the result's status. Commits.

    Parameters:
        position (dict): An open position from storage.exits (position_id, strategy, ticker, holding_type ...)
        exit_reason (str): Why it's closed, e.g. "signal" or "end_of_day"
        conn (Connection): An open database connection
        broker (AlpacaBroker): The broker to cancel and sell through
        shares (dict | None): {ticker: shares} Alpaca holds for the whole account, read once per sweep and
            lowered by every sell sent; None reads it from Alpaca
        price (Decimal | None): The latest price, saved as the sell's request_price; None uses the entry price
        now (datetime | None): The time now, naive UTC; the clock if None
        watch (ExitWatch | None): Starts this position's stuck-close clock when given
        wait_seconds (int): How long to wait for the cancels
        sleep (callable): How to wait; tests pass one that doesn't

    Returns:
        An ExitResult

    Raises:
        pyodbc.Error if the database fails (nothing is sold after a failed read)
    """
    now = now or _utc_now()
    position_id, ticker = position["position_id"], position["ticker"]
    orders = get_position_orders(conn, position_id)
    open_sells = [o for o in orders if o["side"] == "sell" and o["parent_order_id"] is None
                  and o["status"] not in DONE_STATUSES]
    working = [o for o in orders if o["status"] not in DONE_STATUSES and o not in open_sells]
    unanswered = [o for o in working if o["alpaca_order_id"] is None]
    if open_sells or unanswered:
        waiting = (open_sells or unanswered)[-1]
        return ExitResult(position_id, "order_pending",
                          detail=f"{waiting['client_order_id']} is still {waiting['status']}")

    if watch is not None:
        watch.start(position_id, exit_reason, now)
    try:
        answers, unsettled = _cancel_and_wait(broker, working, wait_seconds, sleep)
    except BrokerUnavailable as error:
        trades_log.warning(f"Close of position {position_id} ({ticker}) waits: {error}")
        return ExitResult(position_id, "broker_unavailable", detail=str(error))
    _save_answers(conn, working, answers)
    if unsettled:
        statuses = ", ".join(answers[i].status if i in answers else "not found" for i in unsettled)
        trades_log.warning(f"Close of position {position_id} ({ticker}) waits: {len(unsettled)} order(s) not "
                           f"final after {wait_seconds} s ({statuses})")
        return ExitResult(position_id, "cancel_pending", detail=f"not final after {wait_seconds} s: {statuses}")

    if shares is None:
        try:
            shares = broker.get_positions()
        except BrokerUnavailable as error:
            trades_log.warning(f"Close of position {position_id} ({ticker}) waits: {error}")
            return ExitResult(position_id, "broker_unavailable", detail=str(error))
    held = shares.get(ticker, 0)
    if held < 0:
        if watch is None or watch.first_time(("short", ticker)):
            send_critical(f"Alpaca shows {held} shares of {ticker} (a short). Nothing was sold for position "
                          f"{position_id} ({position['strategy']}); check the account by hand.")
        return ExitResult(position_id, "short", detail=f"Alpaca shows {held} {ticker}")

    remaining = remaining_shares(orders, answers)
    quantity = min(remaining, held)
    trades_log.info(f"Closing position {position_id} ({position['strategy']} {ticker}, {exit_reason}): "
                    f"database {position['shares_held']}, its orders {remaining}, Alpaca {held}, "
                    f"selling {max(quantity, 0)}")
    if quantity <= 0:
        return ExitResult(position_id, "nothing_to_sell")

    request = OrderRequest(strategy=position["strategy"], strategy_id=position["strategy_id"], ticker=ticker,
                           ticker_id=position["ticker_id"], side="sell", quantity=quantity,
                           holding_type=position["holding_type"],
                           price=Decimal(str(price if price is not None else position["avg_entry_price"])),
                           position_id=position_id, exit_reason=exit_reason)
    result = place_order(request, conn, broker, now=now, sleep=sleep)
    if result.status != "rejected":
        shares[ticker] = held - quantity
    status = result.status if result.status in ("rejected", "unknown") else "sent"
    return ExitResult(position_id, status, quantity, result, detail=result.reject_reason or "")
