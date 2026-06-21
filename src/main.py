"""
main.py
Pipline that runs the bot on schedule.
"""

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

import os
from alpaca_client import api
from trader import place_market_order, is_pdt, has_buying_power, has_position
from screener import get_tickers
from data.cleaner import fetch_raw_data, clean_data
from strategies.macd import MACDStrategy
from strategies.rsi import RSIStrategy
from strategies.moving_average import MovingAverageStrategy

import pandas as pd

filters = [
    {"left": "close", "operation": "in_range", "right": [2, 20]},
    {"left": "change", "operation": "greater", "right": 10},
    {"left": "relative_volume_10d_calc", "operation": "greater", "right": 5},
    {"left": "float_shares_outstanding_current", "operation": "in_range", "right": [1000000, 10000000]}
]

account = api.get_account()
clock = api.get_clock()
if not clock.is_open:
    print("Market is closed")
    exit()
tickers = get_tickers(filters)

for ticker in tickers:
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
            current_price = api.get_latest_trade(ticker).price
            quantity = int(float(account.buying_power) * 0.25 / current_price)
            if quantity == 0:
                print("Order not executed: Quantity is 0.")
                continue
            if signal == 1:
                if not is_pdt() and has_buying_power(quantity, current_price):
                    place_market_order(ticker, quantity, side="buy")
            elif signal == -1:
                if not is_pdt() and has_position(ticker):
                    place_market_order(ticker, quantity, side="sell")
        except (AttributeError, Exception):
            print(f"Could not get price of {ticker}, skipping.")
            continue
