"""
orders.py
Place one order: save it, send it to Alpaca with safe retries, and record Alpaca's answer
"""

#Standard Library
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

#Local Imports
from config.constants import ORDER_RETRY_WAITS, STUCK_ORDER_SECONDS, TIME_IN_FORCE
from execution.broker import BrokerUnavailable, DuplicateOrder, OrderRejected
from logger import trades_log
from notifications import send_critical
from storage.orders import (get_stuck_orders, insert_order, save_broker_answer, save_rejection,
                            set_order_status)

CENT = Decimal("0.01")
SUB_PENNY = Decimal("0.0001")
CLIENT_ORDER_ID_LENGTH = 128

@dataclass(frozen=True)
class OrderRequest:
    """One order the engine wants placed, with everything needed to save and send it"""
    strategy: str
    strategy_id: int
    ticker: str
    ticker_id: int
    side: str
    quantity: int
    holding_type: str
    price: Decimal
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    signal_id: int | None = None
    position_id: int | None = None

    def __post_init__(self):
        """Reject a request that can only come from a bug"""
        if self.side not in ("buy", "sell"):
            raise ValueError(f"side {self.side!r} isn't valid. Expected 'buy' or 'sell'")
        if self.quantity <= 0:
            raise ValueError(f"quantity {self.quantity!r} for {self.ticker} isn't valid. Expected 1 or more; "
                             "risk skips zero-quantity buys before they reach execution")
        if not self.price > 0:
            raise ValueError(f"price {self.price!r} for {self.ticker} isn't valid. Expected a number above 0")
        if self.holding_type not in TIME_IN_FORCE:
            raise ValueError(f"holding_type {self.holding_type!r} has no time in force. "
                             f"Expected one of {sorted(TIME_IN_FORCE)}")
        if self.side == "buy" and (self.stop_price is None or self.target_price is None):
            raise ValueError(f"buy of {self.ticker} has stop {self.stop_price!r} and target {self.target_price!r}. "
                             "Expected both, since every buy is a bracket order")

@dataclass(frozen=True)
class OrderResult:
    """What happened to one order request"""
    status: str
    order_id: int | None = None
    client_order_id: str | None = None
    alpaca_order_id: str | None = None
    skip_reason: str | None = None
    reject_reason: str | None = None

def round_to_tick(price) -> Decimal:
    """Round a price to what Alpaca accepts: cents at $1 or more, 4 decimals below $1

    Parameters:
        price (float | Decimal): A price, e.g. 5.0234 or 0.51237

    Returns:
        The rounded price as a Decimal, e.g. Decimal("5.02") or Decimal("0.5124")
    """
    price = Decimal(str(price))
    tick = CENT if price >= 1 else SUB_PENNY
    return price.quantize(tick, rounding=ROUND_HALF_UP)

def exit_prices_valid(price: Decimal, stop_price: Decimal, target_price: Decimal) -> bool:
    """Check that a buy's stop is at least a cent below the price and its target at least a cent above

    Parameters:
        price (Decimal): The price risk sized with
        stop_price (Decimal): The rounded stop-loss price
        target_price (Decimal): The rounded take-profit price

    Returns:
        True if Alpaca can accept the bracket's prices
    """
    return Decimal("0") < stop_price <= price - CENT and target_price >= price + CENT

def make_client_order_id(strategy: str, ticker: str, side: str, now: datetime) -> str:
    """Build the bot's ID for a new order: strategy-ticker-side-UTC time-4 random hex

    Parameters:
        strategy (str): The strategy's NAME
        ticker (str): The ticker symbol
        side (str): "buy" or "sell"
        now (datetime): When the order is saved, in UTC

    Returns:
        The ID, e.g. "momentum-AAPL-buy-20261028T143005Z-3f9a"

    Raises:
        ValueError if the ID is longer than Alpaca's 128 characters
    """
    client_order_id = f"{strategy}-{ticker}-{side}-{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(2)}"
    if len(client_order_id) > CLIENT_ORDER_ID_LENGTH:
        raise ValueError(f"client_order_id {client_order_id!r} is {len(client_order_id)} characters. "
                         f"Expected at most {CLIENT_ORDER_ID_LENGTH}; shorten the strategy NAME")
    return client_order_id

def _send(broker, request: OrderRequest, client_order_id: str, time_in_force: str, stop_price, target_price):
    """Send the order once: a bracket for a buy, a plain market order for a sell"""
    if request.side == "buy":
        return broker.submit_bracket_buy(client_order_id, request.ticker, request.quantity, time_in_force,
                                         stop_price, target_price)
    return broker.submit_market_sell(client_order_id, request.ticker, request.quantity, time_in_force)

def _lookup(broker, client_order_id: str):
    """Ask Alpaca for the order, returning None when it has none or can't be asked"""
    try:
        return broker.find_order(client_order_id)
    except BrokerUnavailable as error:
        trades_log.warning(f"Lookup of {client_order_id} failed: {error}")
        return None

def _submit_with_retries(send, broker, client_order_id: str, waits: list, sleep):
    """Send the order, retrying with the same client_order_id until Alpaca answers

    Before each retry, asks Alpaca whether an earlier send got through, so an order is never placed twice.

    Returns:
        Alpaca's version of the order (a BrokerOrder), or None if every try failed

    Raises:
        OrderRejected if Alpaca refused the order
    """
    for attempt, wait in enumerate([None, *waits], start=1):
        if wait is not None:
            sleep(wait)
            found = _lookup(broker, client_order_id)
            if found is not None:
                return found
        try:
            return send()
        except DuplicateOrder:
            trades_log.info(f"{client_order_id} was already at Alpaca; keeping that order")
            found = _lookup(broker, client_order_id)
            if found is not None:
                return found
        except OrderRejected:
            # A retry can be refused because of the earlier send it repeats (e.g. its buying power is used)
            found = _lookup(broker, client_order_id) if attempt > 1 else None
            if found is not None:
                return found
            raise
        except BrokerUnavailable as error:
            trades_log.warning(f"Send {attempt} of {client_order_id} got no answer: {error}")
    return None

def _save_legs(conn, answer, order_id: int, strategy_id: int, ticker_id: int, signal_id: int | None,
               now: datetime):
    """Save each bracket leg as its own row, linked to its buy"""
    for leg in answer.legs:
        insert_order(conn, client_order_id=leg.client_order_id, alpaca_order_id=leg.alpaca_order_id,
                     side=leg.side, quantity=leg.quantity, order_type=leg.order_type,
                     time_in_force=leg.time_in_force, submitted_at=now, status=leg.status,
                     request_price=leg.stop_price if leg.stop_price is not None else leg.limit_price,
                     strategy_id=strategy_id, ticker_id=ticker_id, signal_id=signal_id, parent_order_id=order_id)

def _utc_now() -> datetime:
    """Return the current UTC time without a time zone, as the database stores it"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def place_order(request: OrderRequest, conn, broker, now: datetime | None = None,
                waits: list = ORDER_RETRY_WAITS, sleep=time.sleep) -> OrderResult:
    """Place one order: save its row, send it to Alpaca, and record what Alpaca answered

    The row is saved and committed before anything is sent, so an order can't exist at Alpaca with no
    record. Buys go as bracket orders (stop-loss + take-profit legs); sells as plain market orders.
    Never raises for something Alpaca did: a rejection or no answer comes back as the result's status.

    Parameters:
        request (OrderRequest): The order to place
        conn (Connection): An open database connection; this function commits
        broker (AlpacaBroker): The broker to send through
        now (datetime | None): The UTC time to save the order with; the clock if None
        waits (list): Seconds to wait before each retry
        sleep (callable): How to wait; tests pass one that doesn't

    Returns:
        An OrderResult whose status is Alpaca's status (e.g. "accepted"), "rejected", "unknown" (no answer
        after every retry; settled later by client_order_id) or "skipped" (invalid_exit_prices, nothing saved)
    """
    time_in_force = TIME_IN_FORCE[request.holding_type]
    stop_price = target_price = None
    if request.side == "buy":
        stop_price, target_price = round_to_tick(request.stop_price), round_to_tick(request.target_price)
        if not exit_prices_valid(Decimal(str(request.price)), stop_price, target_price):
            trades_log.warning(f"Skipped {request.strategy} buy of {request.ticker}: stop {stop_price} or target "
                               f"{target_price} on the wrong side of price {request.price}")
            return OrderResult(status="skipped", skip_reason="invalid_exit_prices")

    now = now or _utc_now()
    client_order_id = make_client_order_id(request.strategy, request.ticker, request.side, now)
    order_id = insert_order(conn, client_order_id=client_order_id, side=request.side, quantity=request.quantity,
                            order_type="market", time_in_force=time_in_force, submitted_at=now,
                            status="submitting", strategy_id=request.strategy_id, ticker_id=request.ticker_id,
                            request_price=Decimal(str(request.price)), signal_id=request.signal_id,
                            position_id=request.position_id)
    conn.commit()

    dollars = Decimal(str(request.price)) * request.quantity
    exits = f" stop {stop_price} target {target_price}" if request.side == "buy" else ""
    trades_log.info(f"{request.side.upper()} {request.strategy} {request.ticker}: {request.quantity} @ ~{request.price} "
                    f"= ${dollars:.2f}{exits} ({time_in_force}, {client_order_id})")

    def send():
        return _send(broker, request, client_order_id, time_in_force, stop_price, target_price)

    try:
        answer = _submit_with_retries(send, broker, client_order_id, waits, sleep)
    except OrderRejected as error:
        save_rejection(conn, order_id, str(error))
        conn.commit()
        trades_log.warning(f"Rejected {client_order_id}: {error}")
        send_critical(f"Order rejected: {request.strategy} {request.side} {request.quantity} {request.ticker}. "
                      f"Alpaca said: {error}")
        return OrderResult(status="rejected", order_id=order_id, client_order_id=client_order_id,
                           reject_reason=str(error))

    if answer is None:
        set_order_status(conn, order_id, "unknown")
        conn.commit()
        trades_log.error(f"No answer for {client_order_id} after {len(waits) + 1} tries; status unknown")
        send_critical(f"Order status unknown: {request.strategy} {request.side} {request.quantity} {request.ticker} "
                      f"({client_order_id}). Alpaca didn't answer; the bot will look it up next cycle.")
        return OrderResult(status="unknown", order_id=order_id, client_order_id=client_order_id)

    save_broker_answer(conn, order_id, answer.alpaca_order_id, answer.status, answer.filled_quantity,
                       answer.filled_price)
    _save_legs(conn, answer, order_id, request.strategy_id, request.ticker_id, request.signal_id, now)
    conn.commit()
    trades_log.info(f"Alpaca has {client_order_id}: {answer.status} ({answer.alpaca_order_id}, "
                    f"{len(answer.legs)} legs)")
    return OrderResult(status=answer.status, order_id=order_id, client_order_id=client_order_id,
                       alpaca_order_id=answer.alpaca_order_id)

def settle_stuck_orders(conn, broker, now: datetime | None = None,
                        stuck_seconds: int = STUCK_ORDER_SECONDS) -> list:
    """Look up orders left at "submitting" or "unknown" and copy Alpaca's version onto them

    Called once per cycle. An order Alpaca has gets its ID, status and legs saved; one Alpaca never got
    becomes "not_sent". If Alpaca can't be asked, the order stays as it is for the next cycle.
    Settling an "unknown" order sends one alert, closing the alert place_order sent.

    Parameters:
        conn (Connection): An open database connection; this function commits after each order
        broker (AlpacaBroker): The broker to look orders up with
        now (datetime | None): The UTC time now; the clock if None
        stuck_seconds (int): How old a row must be before it counts as stuck

    Returns:
        A list of (order_id, new status) for every order settled
    """
    now = now or _utc_now()
    settled = []
    for row in get_stuck_orders(conn, before=now - timedelta(seconds=stuck_seconds)):
        client_order_id = row["client_order_id"]
        try:
            found = broker.find_order(client_order_id)
        except BrokerUnavailable as error:
            trades_log.warning(f"Couldn't settle {client_order_id} ({row['status']}) yet: {error}")
            continue

        if found is None:
            new_status = "not_sent"
            set_order_status(conn, row["order_id"], new_status)
        else:
            new_status = found.status
            save_broker_answer(conn, row["order_id"], found.alpaca_order_id, found.status, found.filled_quantity,
                               found.filled_price)
            _save_legs(conn, found, row["order_id"], row["strategy_id"], row["ticker_id"], row["signal_id"], now)
        conn.commit()

        trades_log.info(f"Settled {client_order_id}: {row['status']} → {new_status}")
        if row["status"] == "unknown":
            send_critical(f"Order {client_order_id} settled: it was unknown, Alpaca's answer is {new_status}.")
        settled.append((row["order_id"], new_status))
    return settled
