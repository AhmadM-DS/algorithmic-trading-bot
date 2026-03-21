"""
macd.py
Implements the MACD trading strategy.
"""

#Third party libraries
import pandas as pd

def generate_signals(df, short_window=12, long_window=26, signal_window=9):
    """
    Generates buy and sell signals based on MACD line crossing the signal line.

    Parameters:
        df: cleaned stock dataframe
        short_window (int): The period for the short-term EMA.
        long_window (int): The period for the long-term EMA.
        signal_window (int): The period for the signal line EMA.
    """

    #Calculate short_window and long_window EMA and MACD Line
    ema_short = df["Close"].ewm(span=short_window).mean()
    ema_long = df["Close"].ewm(span=long_window).mean()
    df["macd_line"] = ema_short - ema_long

    #Calculate Signal Line using X periods
    df["signal_line"] = df["macd_line"].ewm(span=signal_window).mean()

    #Detecting crossovers and generating signals
    #1 for buy, -1 for sell, 0 for hold
    df["signal"] = 0
    df.loc[df["macd_line"] > df["signal_line"], "signal"] = 1
    df.loc[df["macd_line"] < df["signal_line"], "signal"] = -1
    df.loc[df["signal"] == df["signal"].shift(1), "signal"] = 0

    return df    