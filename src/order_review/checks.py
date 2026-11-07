"""
checks.py
The pre-order checks: pure rules on a request and the OrderFacts, each returning a skip code or None
"""

#Standard Library
from dataclasses import dataclass
from datetime import datetime

#Local Imports
from config.constants import LAST_BUY_MINUTES_BEFORE_CLOSE, MAX_PRICE_MOVE_OF_STOP
from order_review.facts import OrderFacts
from risk.decisions import RiskRequest

ORDER_CHECK_CODES = ("market_closed", "too_late_to_buy", "not_tradable", "open_order", "stale_price", "price_moved")

@dataclass(frozen=True)
class PriceCheck:
    """A buy's price as the strategy saw it next to the latest real trade, saved as an order_reviews row

    check_price, check_price_at and price_move are None when the ticker had no trade to check against.
    """
    signal_price: float
    check_price: float | None
    check_price_at: datetime | None
    price_feed: str
    price_move: float | None
    max_price_move: float

    def age_seconds(self, as_of: datetime) -> float | None:
        """Return how old the check price is at as_of, or None without one"""
        return None if self.check_price_at is None else (as_of - self.check_price_at).total_seconds()

def last_buy_minutes(request: RiskRequest) -> int | None:
    """Return how many minutes before the close new buys stop for this request; None means until the close

    The one place the cutoff is looked up, so it can later come from the strategy instead of config.
    """
    return LAST_BUY_MINUTES_BEFORE_CLOSE.get(request.signal.holding_type)

def price_check(request: RiskRequest, facts: OrderFacts) -> PriceCheck | None:
    """Compare a buy's signal price with the ticker's latest trade

    The allowed move is MAX_PRICE_MOVE_OF_STOP of the way from the signal price to the stop, so it follows each
    strategy's own stop. A buy whose stop is missing or not below its price gets no check: place_order skips
    it with invalid_exit_prices.

    Parameters:
        request (RiskRequest): The buy, at the price the strategy decided on
        facts (OrderFacts): This cycle's facts

    Returns:
        The PriceCheck, or None if the stop can't give a limit
    """
    stop = request.signal.stop_price
    if stop is None or not 0 < stop < request.price:
        return None
    max_move = MAX_PRICE_MOVE_OF_STOP * (request.price - stop) / request.price
    trade = facts.latest_trade(request.signal.ticker)
    if trade is None:
        return PriceCheck(request.price, None, None, facts.price_feed, None, max_move)
    move = (trade.price - request.price) / request.price
    return PriceCheck(request.price, trade.price, trade.at, facts.price_feed, move, max_move)

def is_fresh(check: PriceCheck | None, facts: OrderFacts) -> bool:
    """Return True if the check price is recent enough to trust"""
    age = None if check is None else check.age_seconds(facts.as_of)
    return age is not None and age <= facts.max_price_age_seconds

def check_market_open(request: RiskRequest, facts: OrderFacts) -> str | None:
    """Block an order while the market is closed: Alpaca would queue it for the next open

    Returns:
        "market_closed" or None
    """
    return None if facts.market_open() else "market_closed"

def check_last_buy_time(request: RiskRequest, facts: OrderFacts) -> str | None:
    """Block a buy too close to today's close (minutes before that day's close, so early closes work)

    Only while the market is open: outside it market_closed is the reason, and counting this too would
    inflate how often the cutoff fires.

    Returns:
        "too_late_to_buy" or None
    """
    if not facts.market_open():
        return None
    minutes, left = last_buy_minutes(request), facts.minutes_to_close()
    return "too_late_to_buy" if minutes is not None and left is not None and left <= minutes else None

def check_tradable(request: RiskRequest, facts: OrderFacts) -> str | None:
    """Block a buy of a ticker Alpaca can't trade (tickers.is_active = 0)

    Returns:
        "not_tradable" or None
    """
    return "not_tradable" if request.signal.ticker in facts.inactive_tickers else None

def check_open_order(request: RiskRequest, facts: OrderFacts) -> str | None:
    """Block a second buy (or sell) while this strategy already has one out for the ticker

    Returns:
        "open_order" or None
    """
    found = facts.has_open_order(request.strategy_id, request.signal.ticker, request.signal.side)
    return "open_order" if found else None

def check_stale_price(request: RiskRequest, facts: OrderFacts) -> str | None:
    """Block a buy with no recent trade to check its price against (thin ticker, halt, or prices down)

    Returns:
        "stale_price" or None
    """
    check = price_check(request, facts)
    return "stale_price" if check is not None and not is_fresh(check, facts) else None

def check_price_moved(request: RiskRequest, facts: OrderFacts) -> str | None:
    """Block a buy whose price moved more than its limit since the strategy decided

    Returns:
        "price_moved" or None
    """
    check = price_check(request, facts)
    if not is_fresh(check, facts):
        return None
    return "price_moved" if abs(check.price_move) > check.max_price_move else None

BUY_CHECKS = {
    "day": (
        check_market_open,
        check_last_buy_time,
        check_tradable,
        check_open_order,
        check_stale_price,
        check_price_moved,
    ),
}

SELL_CHECKS = (
    check_market_open,
    check_open_order,
)
