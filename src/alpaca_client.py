"""
alpaca_client.py
Responsible for connecting to the Alpaca API.
"""

#Standard Library
import os

#Third Party Library
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi
import requests

#Local imports
from logger import get_logger
logger = get_logger(__name__)

#Load environment variables
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL")

if not all ([API_KEY, SECRET_KEY, BASE_URL]):
    logger.warning("One or more environment variables are missing.")

#Connect to API
try:
    api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)
    logger.info("Successfully connected to Alpaca API.")
except requests.exceptions.RequestException:
    logger.error("Unable to connect to Alpaca API.")