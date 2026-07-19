"""
momentum.py
Implementing the Momentum trading strategy by Warrior Trading.
"""

#Local Imports
from strategies.base_strategy import Strategy
from patterns.candlestick_patterns import BullFlagBreakout, FlatTopBreakout
from logger import get_logger
from market_hours import is_within_window
logger = get_logger(__name__)

"""
Strategy Workflow
Momentum trading looks for stocks that are already pre-filtered by the
screener (high relative volume, small float - see DEFAULT_FILTERS) and
now trending above their moving average while breaking out of one of two
chart patterns: a Bull Flag or a Flat Top. Entries only fire during the
first hours of the session, when momentum stocks are most volatile. Every
entry uses a fixed reward/risk exit: the swing low under the pattern is
the stop, twice that distance is the target, and a red candle closing
before either level is hit is treated as a loss of momentum and an early
exit.
"""

class Momentum(Strategy):
    trading_window = ("09:30", "11:30")
    trend_ema_period = 20
    bull_flag_lookback = 10
    bull_flag_min_gain_pct = 0.08
    flag_lookback = 5
    flat_top_lookback = 10
    flat_top_tolerance_pct = 0.005
    flat_top_min_touches = 2
    volume_multiplier = 1.5
    reward_risk_ratio = 2

    def generate_signals(self):
        """
        Buys on a Bull Flag or Flat Top breakout while price is trending
        above its EMA, then exits at a reward/risk target, a stop-loss at
        the pattern's swing low, or the first red candle - whichever
        comes first.
        """
        trend_ema = self.df["Close"].ewm(span=self.trend_ema_period, adjust=False).mean()

        bull_flag = BullFlagBreakout(
            flagpole_lookback=self.bull_flag_lookback,
            flagpole_min_gain_pct=self.bull_flag_min_gain_pct,
            flag_lookback=self.flag_lookback,
            volume_multiplier=self.volume_multiplier,
        )
        flat_top = FlatTopBreakout(
            lookback=self.flat_top_lookback,
            tolerance_pct=self.flat_top_tolerance_pct,
            min_touches=self.flat_top_min_touches,
            volume_multiplier=self.volume_multiplier,
        )
        bull_matches = bull_flag.calculate(self.df)
        flat_matches = flat_top.calculate(self.df)

        self.df["signal"] = 0
        signal_col = self.df.columns.get_loc("signal")

        in_position = False
        stop_price = None
        target_price = None

        for i in range(len(self.df)):
            row = self.df.iloc[i]

            if not in_position:
                if row["Close"] <= trend_ema.iloc[i]:
                    continue

                bull_match = bull_matches.iloc[i]
                flat_match = flat_matches.iloc[i]
                if bull_match is not None:
                    stop_price = bull_match["flag_low"]
                elif flat_match is not None:
                    window_start = max(0, i - self.flat_top_lookback)
                    stop_price = self.df["Low"].iloc[window_start:i].min()
                else:
                    continue

                risk = row["Close"] - stop_price
                if risk <= 0:
                    continue

                target_price = row["Close"] + risk * self.reward_risk_ratio
                self.df.iloc[i, signal_col] = 1
                in_position = True
            else:
                hit_stop = row["Close"] <= stop_price
                hit_target = row["Close"] >= target_price
                red_candle = row["Close"] < row["Open"]
                if hit_stop or hit_target or red_candle:
                    self.df.iloc[i, signal_col] = -1
                    in_position = False
                    stop_price = None
                    target_price = None

        #Live trading only opens new positions inside the momentum window
        if not is_within_window(*self.trading_window) and self.df.iloc[-1]["signal"] == 1:
            self.df.loc[self.df.index[-1], "signal"] = 0
