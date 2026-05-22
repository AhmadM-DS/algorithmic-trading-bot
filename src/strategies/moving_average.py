"""
moving_average.py
Implements the Moving Average Crossover trading strategy.
Generates buy and sell signals based on the crossover of short-term and long-term moving averages.
"""

#Local imports
from src.strategies.base_strategy import Strategy

#Third party libraries
import pandas as pd

class MovingAverageStrategy(Strategy):
    def __init__(self, name, df, ticker, initial_capital, short_window=9, long_window=21):
        """
        Parameters:
            short_window (int): The period for the short-term moving average.
            long_window (int): The period for the long-term moving average.
        """
        super().__init__(name, df, ticker, initial_capital)
        self.short_window = short_window
        self.long_window = long_window
    
    def generate_signals(self):
            """
            Generates buy and sell signals based on moving average crossover.
            """
            #Calculate short and long moving averages
            self.df["short_ma"] = self.df["Close"].rolling(window=self.short_window).mean()
            self.df["long_ma"] = self.df["Close"].rolling(window=self.long_window).mean()

            #Generate signals (1 for buy, -1 for sell, 0 for hold)
            self.df["signal"] = 0
            self.df.loc[self.df["short_ma"] > self.df["long_ma"], "signal"] = 1 
            self.df.loc[self.df["short_ma"] < self.df["long_ma"], "signal"] = -1