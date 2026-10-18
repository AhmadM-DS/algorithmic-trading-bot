"""
base.py
Define the Strategy base class every strategy inherits from
"""

#Standard Library
from abc import ABC, abstractmethod
from datetime import time

#Third Party Libraries
import pandas as pd

#Local Imports
from strategies.signals import Signal
from data.time_frames import is_allowed, kind, TIME_FRAMES
from config.constants import ENABLED_HOLDING_TYPES, MARKET_OPEN_TIME, MARKET_CLOSE_TIME, SEED_TOLERANCE
from indicators.indicators import candles_needed

REQUIRED_SETTINGS = ["NAME", "TIME_FRAME", "DEFAULT_HOLDING_TYPE", "LOOKBACK_WINDOW", "VERSION"]
market_open = time.fromisoformat(MARKET_OPEN_TIME)
market_close = time.fromisoformat(MARKET_CLOSE_TIME)

class Strategy(ABC):
    """Parent of every strategy"""
    NAME = None
    TIME_FRAME = None
    DEFAULT_HOLDING_TYPE = None
    TRADING_WINDOW = None
    INDICATORS = ()
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

    def check_settings(self, profile: dict):
        """Check that this strategy's settings are complete and can work together

        Missing settings are reported first, on their own. Otherwise every other problem
        (time frame, holding type, trading window, indicators, lookback) is collected and
        reported in one error.

        Parameters:
            profile (dict): The market data profile from get_market_data_profile

        Raises:
            ValueError naming every required setting that is still None,
            or ValueError listing every invalid setting
        """
        missing = []
        problems = []
        largest_need = 0
        largest_indicator = None
        
        for setting in REQUIRED_SETTINGS:
            if getattr(self, setting) is None:
                missing.append(setting)
        if missing:
            raise ValueError(f"{type(self).__name__} is missing required settings: {', '.join(missing)}")

        for indicator in self.INDICATORS:
            if not isinstance(indicator, tuple):
                problems.append(f"INDICATORS entry {indicator!r} is invalid. Expected a tuple like ('rsi', 14)")
                continue
            try:
                need = candles_needed(indicator, SEED_TOLERANCE)
            except ValueError as error:
                problems.append(f"INDICATORS entry {indicator!r} is invalid: {error}")
                continue
            if need > largest_need:
                largest_need = need
                largest_indicator = indicator
        if (not isinstance(self.LOOKBACK_WINDOW, int)
                or isinstance(self.LOOKBACK_WINDOW, bool)
                or self.LOOKBACK_WINDOW < 1):
            problems.append(f"LOOKBACK_WINDOW {self.LOOKBACK_WINDOW!r} is invalid. Expected a whole number of 1 or more")
        elif self.LOOKBACK_WINDOW < largest_need:
            problems.append(f"LOOKBACK_WINDOW {self.LOOKBACK_WINDOW!r} is too short. "
                            f"{largest_indicator!r} needs {largest_need} candles at SEED_TOLERANCE {SEED_TOLERANCE}")

        if self.TRADING_WINDOW is not None:
            if (
                not isinstance(self.TRADING_WINDOW, tuple)
                or len(self.TRADING_WINDOW) != 2
                or not all([isinstance(t, time) for t in (self.TRADING_WINDOW)])
            ):
                problems.append(f"Invalid TRADING_WINDOW {self.TRADING_WINDOW!r}. Expected a tuple of time objects with length of 2")
            else:
                start, end = self.TRADING_WINDOW
                if self.TIME_FRAME in TIME_FRAMES and kind(self.TIME_FRAME) == "session":
                    problems.append(f"A window cannot apply to invalid kind {kind(self.TIME_FRAME)}")
                if start >= end:
                    problems.append(f"Invalid TRADING_WINDOW {self.TRADING_WINDOW!r}. start_time {start!r} cannot be at or after end_time {end!r}")
                if start < market_open or end > market_close:
                    problems.append(f"Invalid TRADING_WINDOW {self.TRADING_WINDOW}. Expected window between ({market_open}-{market_close})")
        
        if self.TIME_FRAME not in TIME_FRAMES:
            problems.append(f"TIME_FRAME {self.TIME_FRAME!r} is unknown. Expected one of {list(TIME_FRAMES)}")
        elif not is_allowed(self.TIME_FRAME, profile):
            problems.append(f"TIME_FRAME {self.TIME_FRAME!r} is shorter than the market data plan's minimum of {profile['min_time_frame_minutes']!r} minutes")
        if self.DEFAULT_HOLDING_TYPE not in ENABLED_HOLDING_TYPES:
            problems.append(f"DEFAULT_HOLDING_TYPE {self.DEFAULT_HOLDING_TYPE!r} isn't enabled. Expected one of {ENABLED_HOLDING_TYPES}")
        if problems:
            raise ValueError(f"{type(self).__name__} has invalid settings: " + "; ".join(problems))
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
