"""
alpaca_client.py
Responsible for connecting to the Alpaca API.
"""

#Standard Library
import os

#Third Party Library
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi

#Load environment variables
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
BASE_URL = os.getenv("ALPACA_BASE_URL")

#Connect to API
api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL)