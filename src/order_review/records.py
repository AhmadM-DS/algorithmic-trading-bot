"""
records.py
What the pre-order review writes: the buy's price check, one log line per skip, and the few alerts agreed in E2
"""

#Standard Library
from datetime import timezone

#Local Imports
from logger import trades_log
from notifications import send_critical
from order_review.checks import ORDER_CHECK_CODES
from order_review.facts import OrderFacts
from order_review.review import OrderReview
from risk.decisions import RiskRequest
from storage.events import insert_bot_event
from storage.order_reviews import insert_order_review
from storage.risk import get_latest_events

PRICES_DOWN = "prices_unavailable"
PRICES_BACK = "prices_available"

def save_order_review(conn, signal_id: int, review: OrderReview) -> bool:
    """Save a reviewed buy's price check as an order_reviews row; sells (no check) save nothing

    Called once the signal is saved. Doesn't commit, so it commits with the signal.

    Parameters:
        conn (Connection): An open database connection
        signal_id (int): The saved signal
        review (OrderReview): What review_order answered

    Returns:
        True if a row was saved
    """
    check = review.price_check
    if check is None:
        return False
    checked_at = None if check.check_price_at is None else \
        check.check_price_at.astimezone(timezone.utc).replace(tzinfo=None)
    insert_order_review(conn, signal_id, signal_price=check.signal_price, check_price=check.check_price,
                        check_price_at=checked_at, price_feed=check.price_feed, price_move=check.price_move,
                        max_price_move=check.max_price_move)
    return True

def _price_detail(review: OrderReview, facts: OrderFacts) -> str:
    """Return the numbers behind a price skip, e.g. "signal $4.10, now $4.32 (+5.4%, limit 1.0%, 12 s old)" """
    check = review.price_check
    if check is None:
        return ""
    if check.check_price is None:
        return f": signal ${check.signal_price:.2f}, no {check.price_feed} trade to check against"
    return (f": signal ${check.signal_price:.2f}, now ${check.check_price:.2f} ({check.price_move:+.1%}, "
            f"limit {check.max_price_move:.1%}, {check.age_seconds(facts.as_of):.0f} s old, "
            f"limit {facts.max_price_age_seconds:.0f} s)")

def log_review(request: RiskRequest, review: OrderReview, facts: OrderFacts, strategy_name: str,
               alert=send_critical) -> str | None:
    """Write one trades.log line for a signal the pre-order checks skipped, and alert if a sell couldn't go out

    Risk's own skips aren't logged here (they're saved silently, as in R1 / R2). Only a sell skipped because
    the market is closed alerts: that should never happen and could carry a day position overnight.

    Parameters:
        request (RiskRequest): The signal reviewed
        review (OrderReview): What review_order answered
        facts (OrderFacts): The facts it was reviewed with
        strategy_name (str): The strategy's name, for the message
        alert (callable): Sends the critical alert; Discord by default

    Returns:
        The logged line, or None if no pre-order check failed
    """
    codes = [code for code in review.decision.failed_checks if code in ORDER_CHECK_CODES]
    if not codes:
        return None
    side, ticker = request.signal.side, request.signal.ticker
    detail = _price_detail(review, facts) if {"stale_price", "price_moved"} & set(codes) else ""
    message = f"{', '.join(codes)}: {strategy_name} {side} {ticker}{detail}"
    trades_log.info(message)
    if side == "sell" and "market_closed" in codes:
        alert(f"Sell of {ticker} for {strategy_name} skipped: the market is closed. If it's a day position it "
              "stays open overnight with only its bracket stop; check the account.")
    return message

def record_price_state(conn, facts: OrderFacts, alert=send_critical) -> str | None:
    """Alert once when the latest-price request starts failing and once when it works again

    The last prices_unavailable / prices_available bot_events row is the state, so an outage alerts once
    whatever the number of cycles or restarts. Commits when it writes.

    Parameters:
        conn (Connection): An open database connection
        facts (OrderFacts): This cycle's facts
        alert (callable): Sends the critical alert; Discord by default

    Returns:
        The event_type saved, or None if nothing changed (or no price was asked for)
    """
    if facts.prices_available is None:
        return None
    latest = get_latest_events(conn, (PRICES_DOWN, PRICES_BACK)).get(None)
    if not facts.prices_available and latest != PRICES_DOWN:
        event, message = PRICES_DOWN, (f"Latest prices ({facts.price_feed}) aren't coming from Alpaca: every buy is "
                                       "skipped as stale_price until they're back. Sells still go out.")
    elif facts.prices_available and latest == PRICES_DOWN:
        event, message = PRICES_BACK, f"Latest prices ({facts.price_feed}) are back; buys are checked again."
    else:
        return None
    insert_bot_event(conn, event, message)
    conn.commit()
    trades_log.warning(message)
    alert(message)
    return event
