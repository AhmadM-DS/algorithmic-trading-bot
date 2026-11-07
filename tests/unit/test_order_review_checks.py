"""
test_order_review_checks.py
Unit tests for the OrderFacts snapshot and each pre-order check
"""

#Standard Library
from dataclasses import replace
from datetime import datetime, timedelta, timezone

#Third Party Libraries
import pytest

#Local Imports
from order_review.checks import (check_last_buy_time, check_market_open, check_open_order, check_price_moved,
                                 check_stale_price, check_tradable, last_buy_minutes, price_check)
from order_review.facts import OpenOrder, OrderFacts, TradePrice
from risk.decisions import RiskRequest
from strategies.signals import Signal

MOMENTUM = 3
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
"""10:00 in New York"""

OPEN = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
CLOSE = datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc)

def facts(as_of=NOW, session=(OPEN, CLOSE), trades=None, inactive=(), orders=(), max_age=120):
    """Build the facts of a normal trading day: AAPL last traded at $10.05 ten seconds ago"""
    if trades is None:
        trades = {"AAPL": TradePrice(10.05, as_of - timedelta(seconds=10))}
    return OrderFacts(as_of=as_of, session_open=session[0], session_close=session[1], price_feed="iex",
                      max_price_age_seconds=max_age, latest_trades=trades, inactive_tickers=frozenset(inactive),
                      open_orders=tuple(orders))

def request(side="buy", ticker="AAPL", price=10.0, stop=9.8, holding_type="day"):
    """Build a request; a $10 buy with a $9.80 stop may move 1% (half of the 2% to its stop)"""
    signal = Signal(side=side, time_frame="15Min", holding_type=holding_type, stop_price=stop if side == "buy" else None,
                    target_price=10.4 if side == "buy" else None, reason="test", strategy_version="1.0.0",
                    ticker=ticker, features={})
    return RiskRequest(signal=signal, strategy_id=MOMENTUM, price=price)

def trade_at(price, seconds_old=10):
    return {"AAPL": TradePrice(price, NOW - timedelta(seconds=seconds_old))}

# --- OrderFacts

def test_facts_need_an_aware_time():
    with pytest.raises(ValueError, match="as_of"):
        facts(as_of=NOW.replace(tzinfo=None), session=(None, None))

def test_facts_need_a_whole_session():
    with pytest.raises(ValueError, match="both"):
        facts(session=(OPEN, None))

def test_minutes_to_close_counts_down_and_is_none_on_a_closed_day():
    assert (facts().minutes_to_close(), facts(session=(None, None)).minutes_to_close()) == (360, None)

# --- market open

@pytest.mark.parametrize("as_of", [OPEN - timedelta(minutes=1), CLOSE, CLOSE + timedelta(hours=2)])
def test_orders_outside_regular_hours_are_blocked(as_of):
    """Block before the open and from the close on, so nothing is queued for the next open"""
    assert check_market_open(request(), facts(as_of=as_of)) == "market_closed"

def test_order_at_the_open_passes():
    assert check_market_open(request(), facts(as_of=OPEN)) is None

def test_closed_day_blocks_every_order():
    """Block on a holiday or weekend (no session in the calendar)"""
    assert check_market_open(request(side="sell"), facts(session=(None, None))) == "market_closed"

# --- last buy time

def test_buy_31_minutes_before_the_close_passes():
    assert check_last_buy_time(request(), facts(as_of=CLOSE - timedelta(minutes=31))) is None

def test_buy_30_minutes_before_the_close_is_too_late():
    assert check_last_buy_time(request(), facts(as_of=CLOSE - timedelta(minutes=30))) == "too_late_to_buy"

@pytest.mark.parametrize("as_of", [CLOSE, CLOSE + timedelta(hours=2)])
def test_cutoff_isnt_counted_once_the_market_is_closed(as_of):
    """Leave after-hours buys to market_closed alone"""
    assert check_last_buy_time(request(), facts(as_of=as_of)) is None

def test_early_close_moves_the_cutoff():
    """Stop day buys at 12:30 on a 13:00 close, not at 15:30"""
    early_close = datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc)
    early = facts(as_of=datetime(2026, 11, 27, 17, 35, tzinfo=timezone.utc),
                  session=(datetime(2026, 11, 27, 14, 30, tzinfo=timezone.utc), early_close))

    assert check_last_buy_time(request(), early) == "too_late_to_buy"

def test_holding_type_without_a_cutoff_buys_until_the_close():
    """Give a holding type with no LAST_BUY_MINUTES_BEFORE_CLOSE entry (swing later) no cutoff"""
    swing = request(holding_type="swing")

    assert (last_buy_minutes(swing), check_last_buy_time(swing, facts(as_of=CLOSE - timedelta(minutes=5)))) == (None, None)

# --- tradable and open orders

def test_inactive_ticker_is_blocked():
    assert check_tradable(request(), facts(inactive={"AAPL"})) == "not_tradable"

def test_open_buy_of_the_same_strategy_blocks_a_second_buy():
    assert check_open_order(request(), facts(orders=[OpenOrder(MOMENTUM, "AAPL", "buy")])) == "open_order"

@pytest.mark.parametrize("order", [OpenOrder(MOMENTUM + 1, "AAPL", "buy"), OpenOrder(MOMENTUM, "TSLA", "buy"),
                                   OpenOrder(MOMENTUM, "AAPL", "sell")])
def test_other_orders_dont_block(order):
    """Ignore another strategy's order, another ticker, and a sell when buying"""
    assert check_open_order(request(), facts(orders=[order])) is None

def test_open_sell_blocks_a_second_sell():
    """Never send two sells for the same shares (could open a short)"""
    assert check_open_order(request(side="sell"), facts(orders=[OpenOrder(MOMENTUM, "AAPL", "sell")])) == "open_order"

# --- price

def test_price_check_limit_is_half_the_way_to_the_stop():
    check = price_check(request(), facts())

    assert (check.signal_price, check.check_price, round(check.price_move, 6), round(check.max_price_move, 6)) == \
           (10.0, 10.05, 0.005, 0.01)

@pytest.mark.parametrize("stop", [None, 10.0, 10.5])
def test_no_price_check_without_a_stop_below_the_price(stop):
    """Leave a buy with no usable stop to place_order's invalid_exit_prices"""
    assert price_check(request(stop=stop), facts()) is None

def test_ticker_without_a_trade_is_stale():
    check = price_check(request(), facts(trades={}))

    assert (check.check_price, check.price_move, check_stale_price(request(), facts(trades={}))) == \
           (None, None, "stale_price")

def test_trade_older_than_the_limit_is_stale():
    assert check_stale_price(request(), facts(trades=trade_at(10.05, seconds_old=121))) == "stale_price"

def test_fresh_trade_passes():
    assert check_stale_price(request(), facts(trades=trade_at(10.05, seconds_old=120))) is None

@pytest.mark.parametrize("price", [10.11, 9.89])
def test_price_moved_past_the_limit_either_way_is_blocked(price):
    """Block a 1.1% move up (chasing) or down (closer to the stop) when 1% is allowed"""
    assert check_price_moved(request(), facts(trades=trade_at(price))) == "price_moved"

def test_price_within_the_limit_passes():
    assert check_price_moved(request(), facts(trades=trade_at(10.09))) is None

def test_stale_price_isnt_also_called_moved():
    """Judge the move only on a fresh price; an old one is only stale"""
    old = facts(trades=trade_at(12.0, seconds_old=600))

    assert (check_stale_price(request(), old), check_price_moved(request(), old)) == ("stale_price", None)

def test_live_plan_limit_comes_from_the_facts():
    """Use the facts' age limit (from the market data profile), not a fixed number"""
    live = replace(facts(trades=trade_at(10.05, seconds_old=61)), max_price_age_seconds=60)

    assert check_stale_price(request(), live) == "stale_price"
