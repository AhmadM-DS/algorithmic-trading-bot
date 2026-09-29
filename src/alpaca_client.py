"""
alpaca_client.py
Responsible for connecting to the Alpaca API.
"""

#Third Party Library
import alpaca_trade_api as tradeapi

#Local imports
from logger import get_logger
logger = get_logger(__name__)


def create_alpaca_client(api_key, secret_key, base_url):
    """Creates an Alpaca trading client
    Parameters:
        api_key: Your Alpaca API Key
        secret_key: Your Alpaca Secret Key
        base_url: The url that connects to Alpaca's REST client (varies by paper or live trading)
    """
    return tradeapi.REST(api_key, secret_key, base_url)
