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

MAX_TICKERS = 20
PROFIT_TARGET = 0.10    # halt strategy once daily ROI >= +10%
LOSS_LIMIT    = -0.05   # halt strategy once daily ROI <= -5%

tickers_cache = []

# Per-day state — all reset at 09:30 screener refresh
signals_executed_today = set()   # (ticker, strategy_name, side) — prevents duplicate orders
strategy_cost_basis    = {}      # strategy_name -> total capital deployed today ($)
strategy_realized_pnl  = {}      # strategy_name -> total realized P&L today ($)
strategy_entry_prices  = {}      # (strategy_name, ticker) -> (entry_price, qty)
halted_strategies      = set()   # strategies shut off for the rest of the day

def reset_daily_state():
    signals_executed_today.clear()
    strategy_cost_basis.clear()
    strategy_realized_pnl.clear()
    strategy_entry_prices.clear()
    halted_strategies.clear()

def is_strategy_halted(name):
    if name in halted_strategies:
        return True
    cost = strategy_cost_basis.get(name, 0)
    if cost == 0:
        return False
    roi = strategy_realized_pnl.get(name, 0) / cost
    if roi >= PROFIT_TARGET:
        halted_strategies.add(name)
        logger.info(f"Strategy {name} halted: profit target reached ({roi:.1%} ROI).")
        send_routine(f"Strategy {name} halted for today: profit target reached ({roi:.1%} ROI).")
        return True
    if roi <= LOSS_LIMIT:
        halted_strategies.add(name)
        logger.info(f"Strategy {name} halted: loss limit reached ({roi:.1%} ROI).")
        send_routine(f"Strategy {name} halted for today: loss limit reached ({roi:.1%} ROI).")
        return True
    return False

def refresh_screener():
    global tickers_cache
    reset_daily_state()
    tickers_cache = get_tickers(Strategy.filters)[:MAX_TICKERS]
    logger.info(f"Screener refreshed. {len(tickers_cache)} tickers found.")
    send_routine(f"Screener refreshed. Adding the following tickers: {tickers_cache}")

def run():
    try:
        if is_market_open():
            if not tickers_cache:
                send_critical("No tickers in cache. Cannot run bot. <@375084779256676353>")
                logger.info("No tickers in cache yet. Skipping run.")
                return
            account = api.get_account()
            for ticker in tickers_cache:
                cleaned_path = CLEANED_DIR / f"{ticker}_cleaned.csv"
                if os.path.exists(cleaned_path):
                    df = pd.read_csv(cleaned_path)
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
                    if is_strategy_halted(strategy.name):
                        continue
                    signal = strategy.get_latest_signal()
                    try:
                        current_price = api.get_latest_trade(ticker).price
                        quantity = int(float(account.buying_power) * 0.25 / current_price)
                        if quantity == 0:
                            send_trades(f"Order not executed. Attempted to purchase 0 shares of {ticker}.")
                            logger.warning("Order not executed: Quantity is 0.")
                            continue
                        if signal == 1:
                            buy_key = (ticker, strategy.name, "buy")
                            if buy_key in signals_executed_today:
                                logger.info(f"Duplicate buy signal skipped: {strategy.name} on {ticker}.")
                                continue
                            result = place_market_order(ticker, quantity, side="buy")
                            if "Order Placed" in result:
                                signals_executed_today.add(buy_key)
                                strategy_cost_basis[strategy.name] = strategy_cost_basis.get(strategy.name, 0) + current_price * quantity
                                strategy_entry_prices[(strategy.name, ticker)] = (current_price, quantity)
                                account = api.get_account()  # refresh buying power after order
                        elif signal == -1:
                            sell_key = (ticker, strategy.name, "sell")
                            if sell_key in signals_executed_today:
                                logger.info(f"Duplicate sell signal skipped: {strategy.name} on {ticker}.")
                                continue
                            if has_position(ticker):
                                result = place_market_order(ticker, quantity, side="sell")
                                if "Order Placed" in result:
                                    signals_executed_today.add(sell_key)
                                    entry = strategy_entry_prices.pop((strategy.name, ticker), None)
                                    if entry:
                                        entry_price, entry_qty = entry
                                        pnl = (current_price - entry_price) * entry_qty
                                        strategy_realized_pnl[strategy.name] = strategy_realized_pnl.get(strategy.name, 0) + pnl
                                    account = api.get_account()  # refresh buying power after order
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
