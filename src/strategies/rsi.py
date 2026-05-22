"""
rsi.py
Implements the RSI trading strategy.
"""

#Local imports
from strategies.base_strategy import Strategy

#Third party libraries
import pandas as pd

class RSIStrategy(Strategy):
    def __init__(self, name, df, ticker, initial_capital, period=14, overbought=70, oversold=30):
        """
        Parameters:
            period (int): The period for calculating RSI.
            overbought (int): The RSI threshold above which the stock is considered overbought.
            oversold (int): The RSI threshold below which the stock is considered oversold.
        """
        super().__init__(name, df, ticker, initial_capital)
        self.period = period
        self.overbought = overbought
        self.oversold = oversold

    def generate_signals(self):
        """
        Generates buy and sell signals based on RSI crossing overbought and oversold thresholds.
        """

        #Calculate gains and loss
        self.df["delta"] = self.df["Close"] - self.df["Close"].shift(1) 
        self.df["gain"] = 0.0
        self.df["loss"] = 0.0
        self.df.loc[self.df["delta"] > 0, "gain"] = self.df["delta"]
        self.df.loc[self.df["delta"] < 0, "loss"] = abs(self.df["delta"])

        #calculate average gain and loss
        self.df["avg_gain"] = self.df["gain"].rolling(window=self.period).mean()
        self.df["avg_loss"] = self.df["loss"].rolling(window=self.period).mean()

        #calculate rsi
        self.df["rsi"] = 100 - (100 / (1 + (self.df["avg_gain"] / self.df["avg_loss"])))

        #generating buy and sell signals
        #1 for buy, -1 for sell, 0 for hold
        self.df["signal"] = 0
        self.df.loc[self.df["rsi"] < self.oversold, "signal"] = 1
        self.df.loc[self.df["rsi"] > self.overbought, "signal"] = -1