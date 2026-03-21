"""
visuals.py
Responsible for visualizing stock data and trading signals using Matplotlib.
"""

#Third party libraries
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

def plot_signals(signals, ticker, strategy, column1, column2, label1, label2):
    """
    Plots the stock price along with buy and sell signals.
    
    Parameters:
        signals: Computed trading signals.
        ticker: The stock symbol for labeling the plot.
    """

    #Plot closing price with moving averages and signals
    _, ax = plt.subplots(figsize=(14, 7))

    #Plot closing price and moving averages
    ax.plot(signals["Date"], signals["Close"], label="Close Price", alpha=0.5)
    ax.plot(signals["Date"], signals[column1], label=label1, alpha=0.8)
    ax.plot(signals["Date"], signals[column2], label=label2, alpha=0.8)

    #Plot buy signals
    ax.scatter(signals.loc[signals["signal"] == 1, "Date"],
            signals.loc[signals["signal"] == 1, "Close"], 
            marker="^", color="green", label="Buy", zorder=5)

    #Plot sell signals
    ax.scatter(signals.loc[signals["signal"] == -1, "Date"],
            signals.loc[signals["signal"] == -1, "Close"], 
            marker="v", color="red", label="Sell", zorder=5)

    ax.set_title(f"{ticker} {strategy} Strategy")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price")
    ax.legend()
    plt.show()

def plot_portfolio_growth(results, stock):
    """
    Plots the growth of the portfolio over time based on the backtest results.

    Parameters:
        results: A dictionary containing the results of the backtest, including the trades and their profits.
    """

    fig, ax = plt.subplots(figsize=(14, 7))

    trades_df = results["trades"]
    sells = trades_df[trades_df["Type"] == "Sell"]
    portfolio_value = results["starting_capital"] + sells["Profit"].cumsum()

    ax.plot(sells["Date"], portfolio_value, label="Portfolio Value", alpha=0.5)

    ax.set_title(f"Portfolio growth over time for {stock}")
    ax.set_xlabel("Date")
    ax.set_ylabel("Amount")
    ax.legend()
    plt.xticks(rotation=45)
    plt.show()