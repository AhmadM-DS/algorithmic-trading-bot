"""
moving_average.py
Implements the Moving Average Crossover trading strategy.
Generates buy and sell signals based on the crossover of short-term and long-term moving averages.
"""

#Third party libraries
import pandas as pd

def generate_signals(df, short_window=9, long_window=21):
    """
    Generates buy and sell signals based on moving average crossover.

    Parameters:
        df: cleaned stock dataframe
        short_window (int): The period for the short-term moving average.
        long_window (int): The period for the long-term moving average.
    """

    #Calculate short and long moving averages
    df["short_ma"] = df["Close"].rolling(window=short_window).mean()
    df["long_ma"] = df["Close"].rolling(window=long_window).mean()

    #Generate signals (1 for buy, -1 for sell, 0 for hold)
    df["signal"] = 0
    df.loc[df["short_ma"] > df["long_ma"], "signal"] = 1 
    df.loc[df["short_ma"] < df["long_ma"], "signal"] = -1

    return df