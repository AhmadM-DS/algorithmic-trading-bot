"""
review.py
Review one order: the risk decision plus the pre-order checks, as the one answer the cycle acts on
"""

#Standard Library
from dataclasses import dataclass, replace

#Local Imports
from config.constants import SKIP_PRIORITY
from order_review.checks import BUY_CHECKS, SELL_CHECKS, PriceCheck, is_fresh, price_check
from order_review.facts import OrderFacts
from risk import Decision, RiskContext, RiskRequest, decide

@dataclass(frozen=True)
class OrderReview:
    """The answer for one signal: the Decision (every failure, risk's and the checks'), the price to send at,
    and the buy's price check to save (None for sells)"""
    decision: Decision
    price: float
    price_check: PriceCheck | None

def _merge(decision: Decision, failures: list) -> Decision:
    """Add the checks' failures to risk's, ordered by SKIP_PRIORITY so the primary reason is the broadest"""
    if not failures:
        return decision
    failed = tuple(sorted(decision.failed_checks + tuple(failures), key=SKIP_PRIORITY.index))
    return replace(decision, approved_quantity=0, skip_reason=failed[0], failed_checks=failed)

def review_order(request: RiskRequest, context: RiskContext, facts: OrderFacts) -> OrderReview:
    """Decide one signal: run risk, then the pre-order checks, and return one answer

    A buy is sized at the latest trade's price when that trade is fresh, so risk checks what the order will
    really cost; otherwise at the signal's price (the buy is skipped as stale anyway). Sells keep risk's
    quantity and only get the market-open and open-order checks: a sell is never blocked by price or tradability.
    Pure: no database, no Alpaca, no clock, so a backtest passes simulated facts and gets the same rules.

    Parameters:
        request (RiskRequest): The signal, at the price the strategy decided on
        context (RiskContext): This cycle's risk snapshot
        facts (OrderFacts): This cycle's market and order facts

    Returns:
        The OrderReview

    Raises:
        ValueError if the side or holding type has no rules
    """
    side, holding_type = request.signal.side, request.signal.holding_type
    if side == "sell":
        failures = [code for check in SELL_CHECKS if (code := check(request, facts)) is not None]
        return OrderReview(_merge(decide(request, context), failures), request.price, None)
    if side != "buy":
        raise ValueError(f"Unknown side {side!r}. Expected 'buy' or 'sell'")
    if holding_type not in BUY_CHECKS:
        raise ValueError(f"No order checks for holding type {holding_type!r}. Expected one of {list(BUY_CHECKS)}")

    check = price_check(request, facts)
    price = check.check_price if is_fresh(check, facts) else request.price
    decision = decide(replace(request, price=price), context)
    failures = [code for check_rule in BUY_CHECKS[holding_type] if (code := check_rule(request, facts)) is not None]
    return OrderReview(_merge(decision, failures), price, check)
