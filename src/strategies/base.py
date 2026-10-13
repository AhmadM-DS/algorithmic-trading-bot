"""
base.py
Define the Strategy base class every strategy inherits from
"""

#Standard Library
from abc import ABC, abstractmethod

#Third Party Libraries
import pandas as pd

#Local Imports
from strategies.signals import Signal

REQUIRED_SETTINGS = ["NAME", "TIME_FRAME", "CAPITAL_BUDGET", "DEFAULT_HOLDING_TYPE", "LOOKBACK_WINDOW", "VERSION"]

class Strategy(ABC):
    """Parent of every strategy"""
    NAME = None
    TIME_FRAME = None
    CAPITAL_BUDGET = None
    DEFAULT_HOLDING_TYPE = None
    STOP_PERCENT_FROM_ENTRY = 0.02
    TARGET_PERCENT_FROM_ENTRY = 0.04
    LOOKBACK_WINDOW = None
    VERSION = None

    @abstractmethod
    def generate_signal(self, ticker: str, candles: pd.DataFrame, position: int) -> Signal | None:
        """Decide whether to buy or sell a ticker from its latest closed candles

        Parameters:
            ticker (str): The stock symbol
            candles (pd.DataFrame): Closed candles, oldest first; work on a copy
            position (int): Shares currently held by this strategy (0 = none)

        Returns:
            A Signal, or None when there is nothing to do
        """
        ...

    def check_settings(self):
        """Check that every required class attribute has been set

        Raises:
            ValueError naming every required setting that is still None
        """
        missing = []
        for setting in REQUIRED_SETTINGS:
            if getattr(self, setting) is None:
                missing.append(setting)
        if missing:
            raise ValueError(f"{type(self).__name__} is missing required settings: {', '.join(missing)}")

    def make_signal(self, ticker: str, side: str, reason: str, entry_price: float, features: dict) -> Signal:
        """Build a Signal from this strategy's settings

        Buys get a stop and target from STOP_PERCENT_FROM_ENTRY and TARGET_PERCENT_FROM_ENTRY.
        Sells close a position, so they get neither.

        Parameters:
            ticker (str): The stock symbol
            side (str): "buy" or "sell"
            reason (str): Why the strategy fired
            entry_price (float): The price the signal is based on
            features (dict): Inputs known at decision time

        Returns:
            A Signal

        Raises:
            ValueError if side isn't "buy" or "sell"
        """
        if side == "buy":
            stop_price = entry_price * (1 - self.STOP_PERCENT_FROM_ENTRY)
            target_price = entry_price * (1 + self.TARGET_PERCENT_FROM_ENTRY)
        elif side == "sell":
            stop_price = None
            target_price = None
        else:
            raise ValueError(f"Unknown side {side!r}. Expected 'buy' or 'sell'")
        return Signal(side=side, time_frame=self.TIME_FRAME, holding_type=self.DEFAULT_HOLDING_TYPE,
                      stop_price=stop_price, target_price=target_price, reason=reason,
                      strategy_version=self.VERSION, ticker=ticker, features=features)
