"""
test_order_review_contract.py
Contract tests for the pre-order review's front door: they import only from the order_review and risk packages
and call only review_order()

The cycle and the backtester both rely on this shape; a redesign of the checks must pass these unchanged.
"""

#Standard Library
from dataclasses import replace
from datetime import datetime, timedelta, timezone

#Third Party Libraries
import pytest

#Local Imports
from order_review import OpenOrder, OrderFacts, TradePrice, review_order
from risk import BrokerPosition, OpenPosition, RiskContext, RiskRequest, StrategyState
from strategies.signals import Signal

LIVE = 3
SHADOW = 4
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
SESSION = (datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc), datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc))

def _request(side="buy", strategy_id=LIVE, ticker="AAPL", price=10.0, holding_type="day"):
    """A $10 buy with a $9.80 stop: sized $250 x 0.20 = $50, may move 1%"""
    buy = side == "buy"
    signal = Signal(side=side, time_frame="15Min", holding_type=holding_type, stop_price=9.8 if buy else None,
                    target_price=10.4 if buy else None, reason="test", strategy_version="1.0.0", ticker=ticker,
                    features={})
    return RiskRequest(signal=signal, strategy_id=strategy_id, price=price)

def _context(kill_switch=False, held=0):
    """A $1,000 account, one live and one shadow strategy, optionally holding AAPL"""
    positions = (OpenPosition(position_id=1, strategy_id=LIVE, ticker="AAPL", holding_type="day", shares_held=held,
                              avg_entry_price=10.0),) if held else ()
    return RiskContext(as_of=NOW, equity=1000.0, buying_power=1000.0,
                       strategies=(StrategyState(strategy_id=LIVE, mode="live", effective_budget=250.0),
                                   StrategyState(strategy_id=SHADOW, mode="shadow", effective_budget=0.0)),
                       open_positions=positions, recent_exits=(),
                       broker_positions=(BrokerPosition("AAPL", held),) if held else (), kill_switch=kill_switch)

def _facts(price=10.05, seconds_old=10, session=SESSION, inactive=(), orders=()):
    """Facts at 10:00 New York with AAPL last traded at price"""
    trades = {} if price is None else {"AAPL": TradePrice(price, NOW - timedelta(seconds=seconds_old))}
    return OrderFacts(as_of=NOW, session_open=session[0], session_close=session[1], price_feed="iex",
                      max_price_age_seconds=120, latest_trades=trades, inactive_tickers=frozenset(inactive),
                      open_orders=tuple(orders))

def test_healthy_buy_is_approved_at_the_fresh_price():
    """Size from the latest trade ($10.05: 4 shares), not the signal's $10 (5 shares), and send at it"""
    review = review_order(_request(), _context(), _facts())

    assert (review.decision.approved_quantity, review.price) == (4, 10.05)

def test_buy_returns_its_price_check_to_save():
    check = review_order(_request(), _context(), _facts()).price_check

    assert (check.signal_price, check.check_price, check.price_feed) == (10.0, 10.05, "iex")

def test_closed_market_skips_a_buy_and_keeps_its_size():
    review = review_order(_request(), _context(), _facts(session=(None, None)))

    assert (review.decision.skip_reason, review.decision.approved_quantity, review.decision.sized_quantity) == \
           ("market_closed", 0, 4)

def test_risk_and_order_failures_are_merged_in_priority_order():
    """List every failure, risk's broadest first, so the bridge table gets them all"""
    review = review_order(_request(), _context(kill_switch=True), _facts(session=(None, None), inactive={"AAPL"}))

    assert review.decision.failed_checks == ("kill_switch", "market_closed", "not_tradable")

def test_stale_price_skips_and_sizes_at_the_signal_price():
    review = review_order(_request(), _context(), _facts(seconds_old=600))

    assert (review.decision.skip_reason, review.price, review.decision.sized_quantity) == ("stale_price", 10.0, 5)

def test_moved_price_is_skipped():
    assert review_order(_request(), _context(), _facts(price=10.2)).decision.skip_reason == "price_moved"

def test_prices_down_skips_every_buy_as_stale():
    review = review_order(_request(), _context(), _facts(price=None))

    assert (review.decision.skip_reason, review.price_check.check_price) == ("stale_price", None)

def test_shadow_buy_still_gets_the_order_checks_recorded():
    """Keep shadow first, and still record what the order checks would have said"""
    review = review_order(_request(strategy_id=SHADOW), _context(), _facts(session=(None, None)))

    assert review.decision.failed_checks == ("shadow", "market_closed")

def test_sell_ignores_price_and_tradability():
    """Sell a held ticker with no price and marked not tradable: a sell is never trapped by those"""
    review = review_order(_request(side="sell"), _context(held=5), _facts(price=None, inactive={"AAPL"}))

    assert (review.decision.approved_quantity, review.price_check) == (5, None)

def test_sell_while_closed_is_skipped():
    review = review_order(_request(side="sell"), _context(held=5), _facts(session=(None, None)))

    assert review.decision.skip_reason == "market_closed"

def test_second_sell_is_skipped():
    review = review_order(_request(side="sell"), _context(held=5), _facts(orders=[OpenOrder(LIVE, "AAPL", "sell")]))

    assert review.decision.skip_reason == "open_order"

def test_sell_failures_follow_priority():
    """Rank market_closed above nothing_to_sell"""
    review = review_order(_request(side="sell"), _context(), _facts(session=(None, None)))

    assert review.decision.failed_checks == ("market_closed", "nothing_to_sell")

def test_same_inputs_give_same_review():
    assert review_order(_request(), _context(), _facts()) == review_order(_request(), _context(), _facts())

def test_holding_type_without_checks_raises():
    with pytest.raises(ValueError, match="holding type"):
        review_order(_request(holding_type="swing"), _context(), _facts())

def test_unknown_side_raises():
    with pytest.raises(ValueError, match="side"):
        review_order(replace(_request(), signal=replace(_request().signal, side="short")), _context(), _facts())
