"""
main.py
Pipline that runs the bot on schedule.
"""

# Standard Library
import time
from pathlib import Path
import requests

# Third Party Libraries
import schedule
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# Local Imports
from db import get_connection, update_heartbeat
from alpaca_client import api, tradeapi
from trader import place_market_order, has_position, sync_order_statuses, size_position
from screener import get_tickers
from cleaner import load_ticker_data
from strategies.base_strategy import Strategy
from strategies.macd import MACDStrategy
from strategies.rsi import RSIStrategy
from strategies.moving_average import MovingAverageStrategy
from market_hours import is_market_open, is_weekend, market_time_slots
from notifications import send_critical, send_routine, send_trades
from risk import DailyRiskState
from logger import get_logger
logger = get_logger(__name__)

MAX_TICKERS = 20

tickers_cache = []
risk_state = DailyRiskState()
market_open_today = False

def send_daily_status():
    """
    Once-a-day health check to make sure bot is running properly.
    """
    global market_open_today
    market_open_today = is_market_open()
    if market_open_today:
        send_routine("Market is open. Bot is running today.")
        logger.info("Market is open. Bot is running today.")
    elif is_weekend():
        send_routine("Market is closed (weekend). Bot didn't run today.")
        logger.info("Market is closed (weekend). Bot didn't run today.")
    else:
        send_routine("Market is closed today. Bot stopped running.")
        logger.info("Market is closed today. Bot stopped running.")

def send_closing_status():
    """
    End-of-day confirmation that the bot ran through today's session and
    stopped when the market closed.
    """
    if not market_open_today:
        return
    send_routine("Market has closed for the day. Bot has stopped running.")
    logger.info("Market has closed for the day. Bot has stopped running.")

def refresh_screener():
    global tickers_cache
    if not is_market_open():
        logger.info("Market is closed. Skipping screener refresh.")
        return
    risk_state.reset_daily_state()
    tickers_cache = get_tickers(Strategy.filters)[:MAX_TICKERS]
    logger.info(f"Screener refreshed. {len(tickers_cache)} tickers found.")
    send_routine(f"Screener refreshed. Adding the following tickers: {tickers_cache}")

def evaluate_and_trade(strategy, ticker, account, risk_state):
    """
    Evaluate one strategy's signal for one ticker and place an order if
    warranted. Returns the (possibly refreshed) account object.
    """
    if risk_state.is_halted(strategy.name):
        return account
    signal = strategy.get_latest_signal()
    try:
        current_price = api.get_latest_trade(ticker).price
        if signal == 1:
            if risk_state.already_executed(ticker, strategy.name, "buy"):
                logger.info(f"Duplicate buy signal skipped: {strategy.name} on {ticker}.")
                return account
            quantity = size_position(account, current_price, strategy.risk_fraction)
            if quantity == 0:
                send_trades(f"Order not executed. Attempted to purchase 0 shares of {ticker}.")
                logger.warning("Order not executed: Quantity is 0.")
                return account
            result = place_market_order(ticker, quantity, side="buy")
            if "Order Placed" in result:
                risk_state.record_buy(ticker, strategy.name, current_price, quantity)
                account = api.get_account()  # refresh buying power after order
        elif signal == -1:
            if risk_state.already_executed(ticker, strategy.name, "sell"):
                logger.info(f"Duplicate sell signal skipped: {strategy.name} on {ticker}.")
                return account
            if has_position(ticker):
                entry_qty = risk_state.get_entry_quantity(strategy.name, ticker)
                if entry_qty is None:
                    logger.warning(f"No recorded entry for {strategy.name} on {ticker}; skipping sell (unknown quantity).")
                    return account
                result = place_market_order(ticker, entry_qty, side="sell")
                if "Order Placed" in result:
                    risk_state.record_sell(ticker, strategy.name, current_price, entry_qty)
                    account = api.get_account()  # refresh buying power after order
    except AttributeError:
        send_critical(f"Could not get price of {ticker}, skipping. <@375084779256676353>")
        logger.warning(f"Could not get price of {ticker}, skipping.")
    return account

def run():
    try:
        if is_market_open():
            if not tickers_cache:
                send_critical("No tickers in cache. Cannot run bot. <@375084779256676353>")
                logger.info("No tickers in cache yet. Skipping run.")
                return
            run_started = time.monotonic()
            account = api.get_account()
            for ticker in tickers_cache:
                df = load_ticker_data(ticker)
                if df is None:
                    continue

                strategies = [
                    MACDStrategy("Macd", df=df, ticker=ticker, initial_capital=10000),
                    MovingAverageStrategy("Moving Average", df=df, ticker=ticker, initial_capital=10000),
                    RSIStrategy("RSI", df=df, ticker=ticker, initial_capital=10000)
                ]
                for strategy in strategies:
                    account = evaluate_and_trade(strategy, ticker, account, risk_state)
            with get_connection() as conn:
                sync_order_statuses(conn)
            elapsed = time.monotonic() - run_started
            logger.info(f"run() completed in {elapsed:.1f}s for {len(tickers_cache)} tickers.")
            if elapsed > 600:
                send_routine(f"run() took {elapsed:.1f}s — approaching the 15-minute slot interval.")
        else:
            logger.warning("Market is closed. Skipping run.")
    except tradeapi.rest.APIError:
        send_critical("Bad API keys / Alpaca rejected request... <@375084779256676353>")
    except requests.exceptions.RequestException:
        send_critical("Cannot connect to Alpaca API... <@375084779256676353>")

def write_heartbeat():
    try:
        with get_connection() as conn:
            update_heartbeat(conn)
    except Exception:
        logger.exception("Failed to write bot heartbeat")

if __name__ == "__main__":
    send_routine("Bot started. <@375084779256676353>")
    write_heartbeat()
    schedule.every(1).minutes.do(write_heartbeat)
    schedule.every().day.at("09:30").do(send_daily_status)
    schedule.every().day.at("09:30").do(refresh_screener)
    for slot in market_time_slots():
        schedule.every().day.at(slot).do(run)
    schedule.every().day.at("16:01").do(send_closing_status)
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
