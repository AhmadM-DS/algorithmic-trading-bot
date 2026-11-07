"""
prices.py
The latest real trade per ticker, for checking a signal's price right before an order (not for candles)
"""

#Standard Library
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

#Third Party Libraries
import requests
from alpaca.common.exceptions import APIError
from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockLatestTradeRequest

#Local Imports
from logger import api_log

class PriceUnavailable(Exception):
    """Alpaca didn't answer the latest-trade request, so no ticker has a current price this cycle"""

@dataclass(frozen=True)
class LatestTrade:
    """One ticker's most recent trade: its price and when it happened (UTC)"""
    price: Decimal
    at: datetime

def get_latest_trades(data_client, tickers: list, feed: str) -> dict:
    """Return the most recent trade of each ticker from one feed, in one request

    On the delayed plan the feed is "iex": real time, but only IEX's trades, so a thin ticker may have none
    for minutes. A ticker with no trade at all isn't in the result.

    Parameters:
        data_client (StockHistoricalDataClient): Alpaca data client from alpaca_client.py
        tickers (list): Ticker symbols
        feed (str): The market data profile's price_feed, "iex" or "sip"

    Returns:
        {ticker: LatestTrade}; empty if tickers is empty

    Raises:
        PriceUnavailable if Alpaca can't be asked
    """
    if not tickers:
        return {}
    request = StockLatestTradeRequest(symbol_or_symbols=list(tickers), feed=DataFeed(feed))
    try:
        trades = data_client.get_stock_latest_trade(request)
    except (APIError, requests.exceptions.RequestException) as error:
        raise PriceUnavailable(f"No latest trades from Alpaca ({feed}): {error}") from error
    api_log.debug(f"latest trades ({feed}): {len(trades)} of {len(tickers)} tickers")
    return {ticker: LatestTrade(price=Decimal(str(trade.price)), at=trade.timestamp.astimezone(timezone.utc))
            for ticker, trade in trades.items()}
