"""
alpaca_client.py
Responsible for connecting to the Alpaca API.
"""

#Third Party Library
from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from execution.rate_limiter import RateLimiter, RateLimitedSession


def _attach_limiter(client):
    if hasattr(client, "_session"):
        client._session = RateLimitedSession(RateLimiter())
    else:
        raise AttributeError(
            f"{type(client).__name__} has no '_session'. alpaca-py may have changed; rate limiter not attached."
        )

def create_alpaca_trading_client(api_key, secret_key, paper=True):
    """Creates an Alpaca trading client
    Parameters:
        api_key: Your Alpaca API Key
        secret_key: Your Alpaca Secret Key
        paper (bool): Alpaca trading mode where PAPER:True, LIVE:False
    """
    trading_client = TradingClient(api_key=api_key, secret_key=secret_key, paper=paper)
    _attach_limiter(trading_client)
    return trading_client

def create_alpaca_shd_client(api_key, secret_key):
    """Creates an Alpaca StockHistoricalDataClient for data handling
    Parameters:
        api_key: Your Alpaca API Key
        secret_key: Your Alpaca Secret Key
    """
    stock_historical_client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)
    _attach_limiter(stock_historical_client)
    return stock_historical_client