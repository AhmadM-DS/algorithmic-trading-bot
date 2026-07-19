"""
WarriorTrading.py
Implementing the Momentum trading strategy by Warrior Trading.
"""

#Standard Library
#Third party library
#Local Imports
from strategies.base_strategy import Strategy
from patterns.candlestick_patterns import FlatTopBreakout
from logger import get_logger
from market_hours import is_within_window
logger = get_logger(__name__)

"""
Strategy Workflow
"""

class Momentum(Strategy):
    trading_window = ("09:30", "11:00")
    flat_top_lookback = 10
    flat_top_tolerance_pct = 0.005
    flat_top_min_touches = 2
    flat_top_volume_multiplier = 1.5

    def generate_signals(self):
        """
        Buys when price breaks out above a flat top resistance level on
        strong volume, and sells once price closes back below the
        resistance level it broke out from (the breakout has failed).
        """
        pattern = FlatTopBreakout(
            lookback=self.flat_top_lookback,
            tolerance_pct=self.flat_top_tolerance_pct,
            min_touches=self.flat_top_min_touches,
            volume_multiplier=self.flat_top_volume_multiplier,
        )
        breakouts = pattern.calculate(self.df)

        self.df["signal"] = 0
        self.df.loc[breakouts.notna(), "signal"] = 1

        #Exit once price closes back below the resistance level it broke out from
        in_position = False
        resistance = None
        signal_col = self.df.columns.get_loc("signal")
        for i in range(len(self.df)):
            if self.df.iloc[i]["signal"] == 1:
                in_position = True
                resistance = breakouts.iloc[i]["resistance"]
            elif in_position and self.df.iloc[i]["Close"] < resistance:
                self.df.iloc[i, signal_col] = -1
                in_position = False

        #Live trading only trades within the momentum window; outside it, don't open new positions
        if not is_within_window(*self.trading_window) and self.df.iloc[-1]["signal"] == 1:
            self.df.loc[self.df.index[-1], "signal"] = 0