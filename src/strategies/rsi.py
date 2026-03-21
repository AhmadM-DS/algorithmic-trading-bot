"""
rsi.py
Implements the RSI trading strategy.
"""

#Third party libraries
import pandas as pd

def generate_signals(df, period=14, overbought=70, oversold=30):
    """
    Generates buy and sell signals based on RSI crossing overbought and oversold thresholds.

    Parameters:
        df: cleaned stock dataframe
        period (int): The period for calculating RSI.
        overbought (int): The RSI threshold above which the stock is considered overbought.
        oversold (int): The RSI threshold below which the stock is considered oversold.
    """

    #Calculate gains and loss
    df["delta"] = df["Close"] - df["Close"].shift(1) 
    df["gain"] = 0.0
    df["loss"] = 0.0
    df.loc[df["delta"] > 0, "gain"] = df["delta"]
    df.loc[df["delta"] < 0, "loss"] = abs(df["delta"])

    #calculate average gain and loss
    df["avg_gain"] = df["gain"].rolling(window=period).mean()
    df["avg_loss"] = df["loss"].rolling(window=period).mean()

    #calculate rsi
    df["rsi"] = 100 - (100 / (1 + (df["avg_gain"] / df["avg_loss"])))

    #generating buy and sell signals
    #1 for buy, -1 for sell, 0 for hold
    df["signal"] = 0
    df.loc[df["rsi"] < oversold, "signal"] = 1
    df.loc[df["rsi"] > overbought, "signal"] = -1
    
    return df