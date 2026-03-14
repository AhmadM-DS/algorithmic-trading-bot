"""
visuals.py
Responsible for visualizing stock data and trading signals using Matplotlib.
"""

#Third party libraries
import matplotlib.pyplot as plt
import pandas as pd

def plot_signals(signals, ticker):
    """
    Plots the stock price along with buy and sell signals.
    
    Parameters:
        signals: Computed trading signals.
        ticker: The stock symbol for labeling the plot.
    """

    #Plot closing price with moving averages and signals
    fig, ax = plt.subplots(figsize=(14, 7))

    #Plot closing price and moving averages
    ax.plot(signals["Date"], signals["Close"], label="Close Price", alpha=0.5)
    ax.plot(signals["Date"], signals["short_ma"], label="9-day MA", alpha=0.8)
    ax.plot(signals["Date"], signals["long_ma"], label="21-day MA", alpha=0.8)

    #Plot buy signals
    ax.scatter(signals.loc[signals["signal"] == 1, "Date"],
            signals.loc[signals["signal"] == 1, "Close"], 
            marker="^", color="green", label="Buy", zorder=5)

    #Plot sell signals
    ax.scatter(signals.loc[signals["signal"] == -1, "Date"],
            signals.loc[signals["signal"] == -1, "Close"], 
            marker="v", color="red", label="Sell", zorder=5)

    ax.set_title(f"{ticker} Moving Average Crossover Strategy")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price")
    ax.legend()
    plt.show()
