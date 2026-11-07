"""
test_order_review_storage.py
Integration tests for E2's database side: open orders, pending buys in the risk snapshot, the OrderFacts builder,
saving reviews, the price outage alert, and keeping tickers.is_active in step with Alpaca
"""

#Standard Library
from datetime import date, datetime, timedelta, timezone

#Third Party Libraries
import pandas as pd
import pytest
import requests
from alpaca.data.models import Trade

#Local Imports
from order_review import (OrderFacts, TradePrice, build_order_facts, record_price_state, review_order,
                          save_order_review)
from order_review.records import PRICES_BACK, PRICES_DOWN
from risk import RiskRequest, build_context
from risk_samples import FakeBroker, add_signal, add_strategy, aware, db_now, events, open_position, ticker_id
from storage.orders import get_open_orders, get_pending_buys, insert_order
from storage.watchlist import set_ticker_active
from strategies.signals import Signal
from watchlist.builder import build_watchlist
from watchlist.tradable import sync_tradable

PROFILE = {"price_feed": "iex", "max_price_age_seconds": 120}

class CommitCounter:
    """Wraps the test connection: counts commits instead of making them, so each test still rolls back"""

    def __init__(self, conn):
        self._conn = conn
        self.commits = 0

    def commit(self):
        self.commits += 1

    def __getattr__(self, name):
        return getattr(self._conn, name)

class FakeDataClient:
    """Stands in for StockHistoricalDataClient's latest-trades call"""

    def __init__(self, trades=None, error=None):
        self.trades, self.error = trades or {}, error

    def get_stock_latest_trade(self, request):
        if self.error is not None:
            raise self.error
        return self.trades

def add_order(conn, strategy_id, side="buy", status="accepted", quantity=5, filled=0, ticker="AAPL", price=10,
              parent_order_id=None, position_id=None, number=1) -> int:
    """Save one order row and return its id"""
    order_id = insert_order(conn, client_order_id=f"e2-{strategy_id}-{ticker}-{side}-{number}", side=side,
                            quantity=quantity, order_type="market", time_in_force="day", submitted_at=db_now(conn),
                            status=status, strategy_id=strategy_id, ticker_id=ticker_id(conn, ticker),
                            request_price=price, parent_order_id=parent_order_id, position_id=position_id,
                            exit_reason="signal" if side == "sell" else None)
    if filled:
        conn.execute("UPDATE orders SET filled_quantity = ? WHERE order_id = ?", (filled, order_id))
    return order_id

def calendar_for(day: date, open_hour=14, close_hour=21) -> dict:
    """A one-day calendar the way market_calendar.get_calendar returns it"""
    return {day: {"open": pd.Timestamp(datetime(day.year, day.month, day.day, open_hour, 30), tz="UTC"),
                  "close": pd.Timestamp(datetime(day.year, day.month, day.day, close_hour, 0), tz="UTC")}}

def buy_request(strategy_id, ticker="AAPL", price=10.0):
    signal = Signal(side="buy", time_frame="15Min", holding_type="day", stop_price=9.8, target_price=10.4,
                    reason="test", strategy_version="1.0.0", ticker=ticker, features={})
    return RiskRequest(signal=signal, strategy_id=strategy_id, price=price)

# --- open orders and pending buys

def test_open_orders_include_unsettled_and_leave_out_done_orders_and_legs(bot_conn):
    """List submitting / unknown / accepted orders; leave out filled, not_sent and bracket legs"""
    strategy_id = add_strategy(bot_conn)
    buy = add_order(bot_conn, strategy_id, status="accepted", number=1)
    add_order(bot_conn, strategy_id, status="unknown", ticker="TSLA", number=2)
    add_order(bot_conn, strategy_id, status="filled", ticker="AMD", number=3)
    add_order(bot_conn, strategy_id, status="not_sent", ticker="NVDA", number=4)
    add_order(bot_conn, strategy_id, side="sell", status="held", parent_order_id=buy, number=5)

    found = {(row["ticker"], row["side"]) for row in get_open_orders(bot_conn) if row["strategy_id"] == strategy_id}

    assert found == {("AAPL", "buy"), ("TSLA", "buy")}

def test_pending_buys_hold_only_the_unfilled_shares(bot_conn):
    """Return 3 of 5 shares still to fill, with the position the filled 2 opened"""
    strategy_id = add_strategy(bot_conn)
    position_id = open_position(bot_conn, strategy_id, shares=2)
    add_order(bot_conn, strategy_id, status="partially_filled", filled=2, position_id=position_id, number=2)
    add_order(bot_conn, strategy_id, status="filled", filled=5, ticker="AMD", number=3)

    pending = [row for row in get_pending_buys(bot_conn) if row["strategy_id"] == strategy_id]

    assert [(row["ticker"], row["unfilled"], float(row["request_price"]), row["position_id"]) for row in pending] == \
           [("AAPL", 3, 10.0, position_id)]

def test_snapshot_counts_a_pending_buy_against_the_budget(bot_conn):
    """Count a sent-but-unfilled $50 buy in the strategy's exposure and position count"""
    strategy_id = add_strategy(bot_conn)
    add_order(bot_conn, strategy_id, status="accepted", quantity=5, price=10)

    context = build_context(bot_conn, FakeBroker(), aware(db_now(bot_conn)), "PAPER")

    assert (context.exposure(strategy_id), context.position_count(strategy_id)) == (50.0, 1)

# --- facts

def test_facts_hold_session_orders_inactive_tickers_and_prices(bot_conn):
    strategy_id = add_strategy(bot_conn)
    add_order(bot_conn, strategy_id)
    ticker_id(bot_conn, "ZZZQ")
    set_ticker_active(bot_conn, "ZZZQ", False)
    now = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
    trade = Trade("AAPL", {"t": "2026-11-09T14:59:55Z", "p": 10.05, "s": 100, "x": "V", "i": 1, "c": ["@"], "z": "C"})

    facts = build_order_facts(bot_conn, FakeDataClient({"AAPL": trade}), now, calendar_for(date(2026, 11, 9)),
                              ["AAPL"], PROFILE)

    assert (facts.market_open(), facts.has_open_order(strategy_id, "AAPL", "buy"), "ZZZQ" in facts.inactive_tickers,
            facts.latest_trade("AAPL").price, facts.prices_available) == (True, True, True, 10.05, True)

def test_failed_price_call_leaves_buys_without_prices(bot_conn):
    now = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
    client = FakeDataClient(error=requests.exceptions.ConnectionError("down"))

    facts = build_order_facts(bot_conn, client, now, calendar_for(date(2026, 11, 9)), ["AAPL"], PROFILE)

    assert (facts.prices_available, facts.latest_trades) == (False, {})

def test_no_buy_signals_ask_alpaca_nothing(bot_conn):
    client = FakeDataClient(error=AssertionError("asked Alpaca"))

    facts = build_order_facts(bot_conn, client, datetime(2026, 11, 8, 15, tzinfo=timezone.utc), {}, [], PROFILE)

    assert (facts.prices_available, facts.market_open()) == (None, False)

# --- saving and the price outage alert

def test_review_is_saved_with_a_naive_utc_time(bot_conn):
    strategy_id = add_strategy(bot_conn)
    signal_id = add_signal(bot_conn, strategy_id, db_now(bot_conn))
    now = aware(db_now(bot_conn))
    facts = OrderFacts(as_of=now, session_open=now - timedelta(hours=1), session_close=now + timedelta(hours=3),
                       price_feed="iex", max_price_age_seconds=120,
                       latest_trades={"AAPL": TradePrice(10.05, now - timedelta(seconds=5))})
    context = build_context(bot_conn, FakeBroker(), now, "PAPER")
    review = review_order(buy_request(strategy_id), context, facts)

    assert save_order_review(bot_conn, signal_id, review) is True
    row = bot_conn.execute("SELECT * FROM order_reviews WHERE signal_id = ?", signal_id).fetchone()
    assert (float(row.check_price), row.check_price_at, float(row.max_price_move)) == \
           (10.05, (now - timedelta(seconds=5)).replace(tzinfo=None), 0.01)

def outage_facts(available):
    return OrderFacts(as_of=datetime(2026, 11, 9, 15, tzinfo=timezone.utc), session_open=None, session_close=None,
                      price_feed="iex", max_price_age_seconds=120, latest_trades={}, prices_available=available)

def test_price_outage_alerts_once_and_once_more_when_back(bot_conn):
    conn, sent = CommitCounter(bot_conn), []

    results = [record_price_state(conn, outage_facts(available), alert=sent.append)
               for available in (False, False, True, True)]

    assert (results, len(sent), conn.commits) == ([PRICES_DOWN, None, PRICES_BACK, None], 2, 2)

def test_no_price_request_changes_nothing(bot_conn):
    assert record_price_state(bot_conn, outage_facts(None), alert=lambda message: None) is None

# --- tradable tickers

def test_sync_switches_tickers_off_and_back_on(bot_conn):
    """Mirror Alpaca both ways, one bot_events row per change, one note for all of them"""
    conn, sent = CommitCounter(bot_conn), []
    for ticker in ("AAPL", "ZZZQ", "BACK"):
        ticker_id(bot_conn, ticker)
    set_ticker_active(bot_conn, "BACK", False)
    saved = {row.ticker for row in bot_conn.execute("SELECT ticker FROM tickers").fetchall()}
    tradable = (saved - {"ZZZQ"}) | {"BACK"}

    changes = sync_tradable(conn, tradable, alert=sent.append)

    states = dict(bot_conn.execute("SELECT ticker, is_active FROM tickers WHERE ticker IN ('ZZZQ', 'BACK')").fetchall())
    assert (changes, states, len(sent)) == ({"off": ["ZZZQ"], "on": ["BACK"]}, {"ZZZQ": False, "BACK": True}, 1)
    assert (len(events(bot_conn, "ticker_not_tradable")), len(events(bot_conn, "ticker_tradable"))) == (1, 1)

def test_sync_never_touches_the_admins_blacklist(bot_conn):
    ticker_id(bot_conn, "GME")
    bot_conn.execute("REVERT;")
    bot_conn.execute("UPDATE tickers SET fill_override = 0 WHERE ticker = 'GME'")
    bot_conn.execute("EXECUTE AS USER = 'test_bot';")
    saved = {row.ticker for row in bot_conn.execute("SELECT ticker FROM tickers").fetchall()}

    sync_tradable(CommitCounter(bot_conn), saved, alert=lambda message: None)

    assert bot_conn.execute("SELECT fill_override FROM tickers WHERE ticker = 'GME'").fetchone()[0] == False

def test_empty_tradable_list_changes_nothing(bot_conn):
    ticker_id(bot_conn, "AAPL")

    assert sync_tradable(CommitCounter(bot_conn), set(), alert=lambda message: None) == {"off": [], "on": []}

def test_new_screener_hit_alpaca_cant_trade_stays_off_the_watchlist(bot_conn):
    final = build_watchlist(bot_conn, ["ZZZQ", "KTTA"], date(2026, 11, 9), "biggest-gainers", 3, 20,
                            tradable={"KTTA"})

    assert "ZZZQ" not in final and "KTTA" in final

def test_new_untradable_screener_hit_is_marked_off_right_away(bot_conn):
    """Save a never-seen hit Alpaca can't trade with is_active = 0 the same day, not at tomorrow's sync"""
    build_watchlist(bot_conn, ["ZZZQ", "KTTA"], date(2026, 11, 9), "biggest-gainers", 3, 20, tradable={"KTTA"})

    states = dict(bot_conn.execute("SELECT ticker, is_active FROM tickers WHERE ticker IN ('ZZZQ', 'KTTA')").fetchall())
    details = [row.details for row in events(bot_conn, "ticker_not_tradable")]
    assert (states, details) == ({"ZZZQ": False, "KTTA": True}, ["ZZZQ: screener hit not in Alpaca's tradable list"])

def test_hit_already_marked_off_gets_no_second_event(bot_conn):
    ticker_id(bot_conn, "ZZZQ")
    set_ticker_active(bot_conn, "ZZZQ", False)

    build_watchlist(bot_conn, ["ZZZQ"], date(2026, 11, 9), "biggest-gainers", 3, 20, tradable=set())

    assert events(bot_conn, "ticker_not_tradable") == []
