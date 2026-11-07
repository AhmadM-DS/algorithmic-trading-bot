"""
builder.py
Build the OrderFacts once per cycle from the trading calendar, the database and one latest-trades request
"""

#Standard Library
from datetime import datetime
from zoneinfo import ZoneInfo

#Third Party Libraries
import pyodbc

#Local Imports
from data.market_calendar import NEW_YORK
from data.prices import PriceUnavailable, get_latest_trades
from logger import trades_log
from order_review.facts import OpenOrder, OrderFacts, TradePrice
from storage.orders import get_open_orders
from storage.watchlist import get_inactive_tickers

class OrderFactsUnavailable(Exception):
    """The database didn't answer, so there are no facts and no orders this cycle"""

def _session(calendar: dict, now: datetime) -> tuple:
    """Return today's (open, close) as datetimes, or (None, None) when the market doesn't open today"""
    day = calendar.get(now.astimezone(ZoneInfo(NEW_YORK)).date())
    if day is None:
        return None, None
    return day["open"].to_pydatetime(), day["close"].to_pydatetime()

def build_order_facts(conn, data_client, now: datetime, calendar: dict, tickers: list, profile: dict) -> OrderFacts:
    """Return this cycle's facts for the pre-order checks

    One Alpaca call at most: the latest trade of every ticker with a buy signal this cycle, from the profile's
    price_feed. If that call fails, the facts have no prices (every buy is skipped as stale_price) and
    prices_available is False; sells don't need a price. Doesn't write anything.

    Parameters:
        conn (Connection): An open database connection
        data_client (StockHistoricalDataClient): Alpaca data client from alpaca_client.py
        now (datetime): The real time now, timezone-aware (not the data clock)
        calendar (dict): Trading days from market_calendar.get_calendar
        tickers (list): The tickers of this cycle's buy signals; empty asks Alpaca nothing
        profile (dict): The market data profile (price_feed, max_price_age_seconds)

    Returns:
        The OrderFacts

    Raises:
        OrderFactsUnavailable if the database didn't answer
    """
    try:
        open_orders = tuple(OpenOrder(row["strategy_id"], row["ticker"], row["side"]) for row in get_open_orders(conn))
        inactive = frozenset(get_inactive_tickers(conn))
    except pyodbc.Error as error:
        raise OrderFactsUnavailable(f"Couldn't read open orders or tickers: {error}") from error

    prices_available, trades = None, {}
    if tickers:
        try:
            raw = get_latest_trades(data_client, tickers, profile["price_feed"])
            prices_available = True
            trades = {ticker: TradePrice(float(trade.price), trade.at) for ticker, trade in raw.items()}
        except PriceUnavailable as error:
            prices_available = False
            trades_log.warning(f"No latest prices this cycle; every buy is skipped as stale_price: {error}")

    session_open, session_close = _session(calendar, now)
    return OrderFacts(as_of=now, session_open=session_open, session_close=session_close,
                      price_feed=profile["price_feed"], max_price_age_seconds=profile["max_price_age_seconds"],
                      latest_trades=trades, inactive_tickers=inactive, open_orders=open_orders,
                      prices_available=prices_available)
