"""
main.py
Pipline that runs the bot on schedule.
"""

#TODO AS WE REFACTOR MAIN.PY, REMOVE OLD IMPORTS
from config.settings import load_env_vars
from config.constants import MAX_TICKERS, UNATTENDED_UPGRADES_LOG_PATH, MARKET_OPEN_TIME, CLOSING_STATUS_TIME, DISCORD_MENTION
from alpaca_client import create_alpaca_trading_client, create_alpaca_shd_client
from market_data import get_latest_price
from alpaca.common.exceptions import APIError

# Standard Library
import time
from datetime import datetime, timedelta
from pathlib import Path
import requests
import os

# Third Party Libraries
import schedule

# Local Imports
from db import get_connection, update_heartbeat, insert_trade, get_inactive_tickers, mark_ticker_inactive
from trader import place_market_order, has_position, sync_order_statuses, size_position, reconcile_bracket_exits
from screener import get_tickers
from cleaner import load_ticker_data
from strategies.base_strategy import Strategy
from strategies.macd import MACDStrategy
from strategies.rsi import RSIStrategy
from strategies.moving_average import MovingAverageStrategy
from strategies.momentum import Momentum
from strategies.ict import ICT
from strategies.supply_demand import SupplyDemand
from market_hours import is_market_open, is_weekend, market_time_slots
from notifications import send_critical, send_routine, send_trades
from risk import DailyRiskState
from logger import legacy_log as logger


unattended_upgrade_log = Path(UNATTENDED_UPGRADES_LOG_PATH)

tickers_cache = []
inactive_tickers = set()
risk_state = DailyRiskState()
market_open_today = False
market_closed_logged = False
ticker_cache_empty = False
ict_only_today = False



def get_startup_reason():
    """
    Best-effort explanation for why the process is starting or has restarted.
    """
    try:
        lines = unattended_upgrade_log.read_text().splitlines()
    except OSError:
        return "manual start or deploy"
    cutoff = datetime.now() - timedelta(minutes=10)
    for line in reversed(lines):
        if "All upgrades installed" not in line:
            continue
        try:
            ts = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if ts >= cutoff:
            return "automatic system security updates (unattended-upgrades/needrestart)"
        break
    return "manual start or deploy"

def load_inactive_tickers():
    global inactive_tickers
    try:
        with get_connection() as conn:
            inactive_tickers = get_inactive_tickers(conn)
        logger.info(f"Loaded {len(inactive_tickers)} inactive tickers from the database.")
    except Exception:
        logger.exception("Failed to load inactive tickers from the database.")

def send_daily_status():
    """
    Once-a-day health check to make sure bot is running properly.
    """
    global market_open_today
    market_open_today = is_market_open(trading_client)
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
    global tickers_cache, ticker_cache_empty
    if not is_market_open(trading_client):
        logger.info("Market is closed. Skipping screener refresh.")
        return
    ticker_cache_empty = False
    risk_state.reset_daily_state()
    screened = [t for t in get_tickers(Strategy.filters) if t not in inactive_tickers]
    tickers_cache = screened[:MAX_TICKERS]
    logger.info(f"Screener refreshed. {len(tickers_cache)} tickers found.")
    send_routine(f"Screener refreshed. Adding the following tickers: {tickers_cache}")

def evaluate_and_trade(strategy, ticker, account, risk_state, conn):
    """
    Evaluate one strategy's signal for one ticker and place an order if
    warranted. Returns the (possibly refreshed) account object.
    """
    if risk_state.is_halted(strategy.name):
        return account
    signal = strategy.get_latest_signal()
    try:
        current_price = get_latest_price(data_client=stock_data_client, ticker=ticker)
        if signal == 1:
            if risk_state.already_executed(ticker, strategy.name, "buy"):
                logger.info(f"Duplicate buy signal skipped: {strategy.name} on {ticker}.")
                return account
            quantity = size_position(account, current_price, strategy.risk_fraction)
            if quantity == 0:
                send_trades(f"Order not executed. Attempted to purchase 0 shares of {ticker}.")
                logger.warning("Order not executed: Quantity is 0.")
                return account
            result = place_market_order(trading_client, conn, ticker, quantity, side="buy", price=current_price)
            if "Order Placed" in result:
                risk_state.record_buy(ticker, strategy.name, current_price, quantity)
                insert_trade(conn, strategy.name, ticker, side="buy", quantity=quantity,
                             price=current_price, trade_type="Live", order_id=result["Order_ID"])
                account = trading_client.get_account()  # refresh buying power after order
            elif result.get("Inactive"):
                inactive_tickers.add(ticker)
                mark_ticker_inactive(conn, ticker, result["Order Failed"])
        elif signal == -1:
            if risk_state.already_executed(ticker, strategy.name, "sell"):
                logger.info(f"Duplicate sell signal skipped: {strategy.name} on {ticker}.")
                return account
            if has_position(trading_client, ticker):
                entry_qty = risk_state.get_entry_quantity(strategy.name, ticker)
                if entry_qty is None:
                    logger.warning(f"No recorded entry for {strategy.name} on {ticker}; skipping sell (unknown quantity).")
                    return account
                entry_price = risk_state.get_entry_price(strategy.name, ticker)
                result = place_market_order(trading_client, conn, ticker, entry_qty, side="sell", price=current_price, entry_price=entry_price)
                if "Order Placed" in result:
                    profit = (current_price - entry_price) * entry_qty if entry_price is not None else None
                    risk_state.record_sell(ticker, strategy.name, current_price, entry_qty)
                    insert_trade(conn, strategy.name, ticker, side="sell", quantity=entry_qty,
                                 price=current_price, trade_type="Live", profit=profit, order_id=result["Order_ID"])
                    account = trading_client.get_account()  # refresh buying power after order
                elif result.get("Inactive"):
                    inactive_tickers.add(ticker)
                    mark_ticker_inactive(conn, ticker, result["Order Failed"])
    except AttributeError:
        send_critical(f"Could not get price of {ticker}, skipping. {DISCORD_MENTION}")
        logger.warning(f"Could not get price of {ticker}, skipping.")
    return account

def trade_ICT():
    ticker = 'SPY'
    with get_connection() as conn:
        reconcile_bracket_exits(trading_client, conn, risk_state)
        df = load_ticker_data(ticker)
        strategy = ICT("ICT", df=df, ticker=ticker, initial_capital=10000)
        account = trading_client.get_account()
        account = evaluate_and_trade(strategy, ticker, account, risk_state, conn)
        sync_order_statuses(trading_client, conn)

def run():
    global market_closed_logged, ticker_cache_empty, ict_only_today
    try:
        if is_market_open(trading_client):
            market_closed_logged = False
            if not tickers_cache:
                if not ticker_cache_empty:
                    send_critical(f"No tickers in cache for initial run. {DISCORD_MENTION}")
                    logger.info("No tickers in cache for initial run, switching to plan B.")
                    ticker_cache_empty = True
                if not ict_only_today:
                    send_critical(f"Only trading ICT on SPY today. {DISCORD_MENTION}")
                    logger.info("Only trading ICT on SPY today.")
                    ict_only_today = True
                trade_ICT()
                return
            run_started = time.monotonic()
            account = trading_client.get_account()
            with get_connection() as conn:
                reconcile_bracket_exits(trading_client, conn, risk_state)
                for ticker in tickers_cache:
                    if ticker in inactive_tickers:
                        continue
                    df = load_ticker_data(ticker)
                    if df is None:
                        continue

                    strategies = [
                        MACDStrategy("Macd", df=df, ticker=ticker, initial_capital=10000),
                        MovingAverageStrategy("Moving Average", df=df, ticker=ticker, initial_capital=10000),
                        RSIStrategy("RSI", df=df, ticker=ticker, initial_capital=10000),
                        Momentum("Momentum", df=df, ticker=ticker, initial_capital=10000),
                        ICT("ICT", df=df, ticker=ticker, initial_capital=10000),
                        SupplyDemand("Supply & Demand", df=df, ticker=ticker, initial_capital=10000)
                    ]
                    for strategy in strategies:
                        account = evaluate_and_trade(strategy, ticker, account, risk_state, conn)
                sync_order_statuses(trading_client, conn)
            elapsed = time.monotonic() - run_started
            logger.info(f"run() completed in {elapsed:.1f}s for {len(tickers_cache)} tickers.")
            if elapsed > 600:
                send_routine(f"run() took {elapsed:.1f}s — approaching the 15-minute slot interval.")
        else:
            if not market_closed_logged:
                logger.warning("Market is closed. Skipping run.")
                market_closed_logged = True
    except APIError as e:
        logger.exception("Alpaca API rejected a request in run().")
        send_critical(f"Alpaca API error in run(): {e}. {DISCORD_MENTION}")
    except requests.exceptions.RequestException as e:
        logger.exception("Cannot connect to Alpaca API in run().")
        send_critical(f"Cannot connect to Alpaca API in run(): {e}. {DISCORD_MENTION}")

def write_heartbeat():
    try:
        with get_connection() as conn:
            update_heartbeat(conn)
    except Exception:
        logger.exception("Failed to write bot heartbeat")

if __name__ == "__main__":
    # Load environment variables and set the trading mode
    trading_mode = load_env_vars()
    #Create the alpaca client
    trading_client = create_alpaca_trading_client(api_key=os.environ[f"ALPACA_API_KEY_{trading_mode}"], secret_key=os.environ[f"ALPACA_SECRET_KEY_{trading_mode}"], paper=(trading_mode == "PAPER"))
    stock_data_client = create_alpaca_shd_client(api_key=os.environ[f"ALPACA_API_KEY_{trading_mode}"], secret_key=os.environ[f"ALPACA_SECRET_KEY_{trading_mode}"])
    if trading_mode == "LIVE":
        send_critical(f"Bot started in {trading_mode} mode. Reason: {get_startup_reason()}. {DISCORD_MENTION}")
    else:
        send_routine(f"Bot started in {trading_mode} mode. Reason: {get_startup_reason()}. {DISCORD_MENTION}")

    load_inactive_tickers()
    write_heartbeat()
    schedule.every(1).minutes.do(write_heartbeat)
    schedule.every().day.at(MARKET_OPEN_TIME).do(send_daily_status)
    schedule.every().day.at(MARKET_OPEN_TIME).do(refresh_screener)
    for slot in market_time_slots():
        schedule.every().day.at(slot).do(run)
    schedule.every().day.at(CLOSING_STATUS_TIME).do(send_closing_status)
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        send_routine("Manually stopped the bot.")
    except Exception as e:
        logger.exception("Bot crashed unexpectedly")
        send_critical(f"CRITICAL: Bot crashed. Reason: {e} {DISCORD_MENTION}")
        raise
