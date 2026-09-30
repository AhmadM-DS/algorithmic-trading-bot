"""
alpaca_client.py
Responsible for connecting to the Alpaca API.
"""

#Third Party Library
from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient

#Local imports
from logger import get_logger
logger = get_logger(__name__)


def create_alpaca_trading_client(api_key, secret_key, paper=True):
    """Creates an Alpaca trading client
    Parameters:
        api_key: Your Alpaca API Key
        secret_key: Your Alpaca Secret Key
        paper (bool): Alpaca trading mode where PAPER:True, LIVE:False
    """
    return TradingClient(api_key=api_key, secret_key=secret_key, paper=paper)

def create_alpaca_shd_client(api_key, secret_key):
    """Creates an Alpaca StockHistoricalDataClient for data handling
    Parameters:
        api_key: Your Alpaca API Key
        secret_key: Your Alpaca Secret Key
    """
    return StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)