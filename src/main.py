"""
main.py
Pipline that runs the bot on schedule.
"""

# Standard Library
import os
import time
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
CLEANED_DIR = BASE_DIR / "data" / "cleaned"
import requests

# Third Party Libraries
import pandas as pd
import schedule
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# Local Imports
from db import get_connection
from alpaca_client import api, tradeapi
from trader import place_market_order, has_position, sync_order_statuses
from screener import get_tickers
from cleaner import fetch_raw_data, clean_data
from strategies.base_strategy import Strategy
from strategies.macd import MACDStrategy
from strategies.rsi import RSIStrategy
from strategies.moving_average import MovingAverageStrategy
from market_hours import is_market_open, market_time_slots
from notifications import send_critical, send_routine, send_trades
from logger import get_logger
logger = get_logger(__name__)

tickers_cache = []
def refresh_screener():
    global tickers_cache
    tickers_cache = get_tickers(Strategy.filters)
    logger.info(f"Screener refreshed. {len(tickers_cache)} tickers found.")
    send_routine(f"Screener refreshed. Adding the following tickers: {tickers_cache}")

def run():
    try:
        if is_market_open():
            if not tickers_cache:
                send_critical("No tickers in cache. Cannot run bot. <@375084779256676353>")
                logger.info("No tickers in cache yet. Skipping run.")
                return
            for ticker in tickers_cache:
                if os.path.exists(f"data/cleaned/{ticker}_cleaned.csv"):
                    df = pd.read_csv(f"data/cleaned/{ticker}_cleaned.csv")
                else:
                    raw_df = fetch_raw_data(ticker, start_date='2020-01-01', end_date='2023-01-01')
                    if raw_df is None:
                        continue
                    df = clean_data(ticker)

                strategies = [
                    MACDStrategy("Macd", df=df, ticker=ticker, initial_capital=10000),
                    MovingAverageStrategy("Moving Average", df=df, ticker=ticker, initial_capital=10000),
                    RSIStrategy("RSI", df=df, ticker=ticker, initial_capital=10000)
                ]
                for strategy in strategies:
                    signal = strategy.get_latest_signal()
                    try:
                        account = api.get_account()
                        current_price = api.get_latest_trade(ticker).price
                        quantity = int(float(account.buying_power) * 0.25 / current_price)
                        if quantity == 0:
                            send_trades(f"Order not executed. Attempted to purchase 0 shares of {ticker}.")
                            logger.warning("Order not executed: Quantity is 0.")
                            continue
                        if signal == 1:
                            place_market_order(ticker, quantity, side="buy")
                        elif signal == -1:
                            if has_position(ticker):
                                place_market_order(ticker, quantity, side="sell")
                    except AttributeError:
                        send_critical(f"Could not get price of {ticker}, skipping. <@375084779256676353>")
                        logger.warning(f"Could not get price of {ticker}, skipping.")
                        continue
            with get_connection() as conn:
                sync_order_statuses(conn)
        else:
            logger.warning("Market is closed. Skipping run.")
    except tradeapi.rest.APIError:
        send_critical("Bad API keys / Alpaca rejected request... <@375084779256676353>")
    except requests.exceptions.RequestException:
        send_critical("Cannot connect to Alpaca API... <@375084779256676353>")

if __name__ == "__main__":
    send_routine("Bot started. <@375084779256676353>")
    schedule.every().day.at("09:30").do(refresh_screener)
    for slot in market_time_slots():
        schedule.every().day.at(slot).do(run)
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        send_routine("Manually stopped the bot.")
    except Exception as e:
        logger.exception("Bot crashed unexpectedly")
        send_critical(f"CRITICAL: Bot crashed. Reason: {e} <@375084779256676353>")
        raise