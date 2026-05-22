"""
macd.py
Implements the MACD trading strategy.
"""

#Local imports
from strategies.base_strategy import Strategy

#Third party libraries
import pandas as pd

class MACDStrategy(Strategy):
    def __init__(self, name, df, ticker, initial_capital, short_window=12, long_window=26, signal_window=9):
        """
        Parameters:
            short_window (int): The period for the short-term EMA.
            long_window (int): The period for the long-term EMA.
            signal_window (int): The period for the signal line EMA.
        """
        super().__init__(name, df, ticker, initial_capital)
        self.short_window = short_window
        self.long_window = long_window
        self.signal_window = signal_window

    def generate_signals(self):
        """
        Generates buy and sell signals based on MACD line crossing the signal line.

        Parameters:
            short_window (int): The period for the short-term EMA.
            long_window (int): The period for the long-term EMA.
            signal_window (int): The period for the signal line EMA.
        """
        ema_short = self.df["Close"].ewm(span=self.short_window).mean()
        ema_long = self.df["Close"].ewm(span=self.long_window).mean()
        self.df["macd_line"] = ema_short - ema_long

        #Calculate Signal Line using X periods
        self.df["signal_line"] = self.df["macd_line"].ewm(span=self.signal_window).mean()

        #Detecting crossovers and generating signals
        #1 for buy, -1 for sell, 0 for hold
        self.df["signal"] = 0
        self.df.loc[self.df["macd_line"] > self.df["signal_line"], "signal"] = 1
        self.df.loc[self.df["macd_line"] < self.df["signal_line"], "signal"] = -1
        self.df.loc[self.df["signal"] == self.df["signal"].shift(1), "signal"] = 0