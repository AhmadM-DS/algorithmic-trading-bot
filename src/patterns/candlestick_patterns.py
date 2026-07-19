"""
candlestick_patterns.py
Detects the following price-action patterns:
    -Fair Value Gap
    -Bull Flag Breakout
    -Flat Top Breakout
    -Liquidity Sweep
    -Market Structure Shift (CHoCH)
    ADD TO LIST AS WE DETECT MORE
"""

#Standard Library
#Third party library
import pandas as pd
#Local Imports
from patterns.base_pattern import Pattern

class FairValueGap(Pattern):
    """
    A Fair Value Gap (FVG) is a 3-candle imbalance where the first candle's
    wick never overlaps with the third candle's wick, leaving a gap in price
    that the middle candle blew through. Price tends to revisit that gap
    before continuing in the direction of the original move.
    """
    def __init__(self, min_gap_pct=0.0):
        """
        Parameters:
            min_gap_pct (float): Minimum gap size, as a fraction of the middle
                candle's close, required to count the gap (filters out noise).
        """
        self.min_gap_pct = min_gap_pct

    def _evaluate(self, first, second, third):
        if first["High"] < third["Low"]:
            gap_low, gap_high = first["High"], third["Low"]
            direction = "bullish"
        elif first["Low"] > third["High"]:
            gap_low, gap_high = third["High"], first["Low"]
            direction = "bearish"
        else:
            return None

        mid_close = second["Close"]
        gap_pct = (gap_high - gap_low) / mid_close if mid_close else 0
        if gap_pct < self.min_gap_pct:
            return None

        return {
            "direction": direction,
            "gap_low": gap_low,
            "gap_high": gap_high,
            "gap_pct": gap_pct,
        }

    def calculate(self, df):
        """Batch mode: For backtesting on full historical data"""
        matches = [None] * len(df)
        for i in range(2, len(df)):
            matches[i] = self._evaluate(df.iloc[i - 2], df.iloc[i - 1], df.iloc[i])
        return pd.Series(matches, index=df.index, name="fair_value_gap")

    def update(self, candles):
        """Streaming mode: For paper & live trading, needs the last 3 candles"""
        if len(candles) < 3:
            return None
        first, second, third = candles[-3], candles[-2], candles[-1]
        return self._evaluate(first, second, third)


class BullFlagBreakout(Pattern):
    """
    A bull flag is a strong upward move (the flagpole) followed by a tight,
    shallow pullback/consolidation (the flag). The pattern confirms once
    price breaks back above the flag's high, ideally on rising volume.
    """
    def __init__(self, flagpole_lookback=10, flagpole_min_gain_pct=0.08,
                 flag_lookback=5, max_pullback_pct=0.5, volume_multiplier=1.2):
        """
        Parameters:
            flagpole_lookback (int): Candles used to measure the initial rally.
            flagpole_min_gain_pct (float): Minimum rally size (as a fraction of
                the starting close) required to count as a flagpole.
            flag_lookback (int): Candles used to measure the consolidation.
            max_pullback_pct (float): Maximum retracement of the flagpole's
                range allowed during the flag before it's considered invalid.
            volume_multiplier (float): How much bigger the breakout candle's
                volume must be than the flag's average volume.
        """
        self.flagpole_lookback = flagpole_lookback
        self.flagpole_min_gain_pct = flagpole_min_gain_pct
        self.flag_lookback = flag_lookback
        self.max_pullback_pct = max_pullback_pct
        self.volume_multiplier = volume_multiplier

    def _evaluate(self, flagpole, flag, breakout):
        pole_start = flagpole["Close"].iloc[0]
        pole_high = flagpole["High"].max()
        if pole_start <= 0:
            return None

        flagpole_gain_pct = (pole_high - pole_start) / pole_start
        if flagpole_gain_pct < self.flagpole_min_gain_pct:
            return None

        flagpole_range = pole_high - flagpole["Low"].min()
        if flagpole_range <= 0:
            return None

        flag_low = flag["Low"].min()
        pullback_pct = (pole_high - flag_low) / flagpole_range
        if pullback_pct > self.max_pullback_pct:
            return None

        flag_high = flag["High"].max()
        avg_flag_volume = flag["Volume"].mean()
        volume_confirmed = avg_flag_volume > 0 and breakout["Volume"] >= avg_flag_volume * self.volume_multiplier

        if breakout["Close"] <= flag_high or not volume_confirmed:
            return None

        return {
            "flagpole_gain_pct": flagpole_gain_pct,
            "flag_high": flag_high,
            "flag_low": flag_low,
            "breakout_price": breakout["Close"],
        }

    def calculate(self, df):
        """Batch mode: For backtesting on full historical data"""
        window = self.flagpole_lookback + self.flag_lookback
        matches = [None] * len(df)
        for i in range(window, len(df)):
            flagpole = df.iloc[i - window : i - self.flag_lookback]
            flag = df.iloc[i - self.flag_lookback : i]
            breakout = df.iloc[i]
            matches[i] = self._evaluate(flagpole, flag, breakout)
        return pd.Series(matches, index=df.index, name="bull_flag_breakout")

    def update(self, candles):
        """Streaming mode: For paper & live trading, needs the full flagpole+flag window plus the latest candle"""
        window = self.flagpole_lookback + self.flag_lookback
        if len(candles) < window + 1:
            return None
        recent = pd.DataFrame(list(candles[-(window + 1):]))
        flagpole = recent.iloc[: self.flagpole_lookback]
        flag = recent.iloc[self.flagpole_lookback : window]
        breakout = recent.iloc[-1]
        return self._evaluate(flagpole, flag, breakout)


class FlatTopBreakout(Pattern):
    """
    A flat top forms when price repeatedly tests the same resistance level
    without breaking through it, building a horizontal ceiling. The pattern
    confirms once a candle closes above that resistance, ideally on volume
    higher than what built the flat top.
    """
    def __init__(self, lookback=10, tolerance_pct=0.005, min_touches=2, volume_multiplier=1.5):
        """
        Parameters:
            lookback (int): Candles used to establish the resistance level.
            tolerance_pct (float): How close a candle's high must be to the
                lookback window's max high to count as "touching" resistance.
            min_touches (int): Minimum number of touches required for the
                resistance level to count as a flat top.
            volume_multiplier (float): How much bigger the breakout candle's
                volume must be than the flat top window's average volume.
        """
        self.lookback = lookback
        self.tolerance_pct = tolerance_pct
        self.min_touches = min_touches
        self.volume_multiplier = volume_multiplier

    def _evaluate(self, window, breakout):
        resistance = window["High"].max()
        if resistance <= 0:
            return None

        touches = (window["High"] >= resistance * (1 - self.tolerance_pct)).sum()
        if touches < self.min_touches:
            return None

        avg_volume = window["Volume"].mean()
        volume_confirmed = avg_volume > 0 and breakout["Volume"] >= avg_volume * self.volume_multiplier

        if breakout["Close"] <= resistance or not volume_confirmed:
            return None

        return {
            "resistance": resistance,
            "touches": int(touches),
            "breakout_price": breakout["Close"],
        }

    def calculate(self, df):
        """Batch mode: For backtesting on full historical data"""
        matches = [None] * len(df)
        for i in range(self.lookback, len(df)):
            window = df.iloc[i - self.lookback : i]
            breakout = df.iloc[i]
            matches[i] = self._evaluate(window, breakout)
        return pd.Series(matches, index=df.index, name="flat_top_breakout")

    def update(self, candles):
        """Streaming mode: For paper & live trading, needs the lookback window plus the latest candle"""
        if len(candles) < self.lookback + 1:
            return None
        recent = pd.DataFrame(list(candles[-(self.lookback + 1):]))
        window = recent.iloc[:-1]
        breakout = recent.iloc[-1]
        return self._evaluate(window, breakout)


class LiquiditySweep(Pattern):
    """
    A liquidity sweep is a single candle that pushes through a recent swing
    low (bullish) or swing high (bearish) - clearing out the stop orders
    resting there - and is then immediately rejected. The sweep is only
    valid if the following candle fails to exceed or close beyond the
    sweep candle's extreme.
    """
    def __init__(self, swing_lookback=10):
        """
        Parameters:
            swing_lookback (int): Candles used to establish the prior swing
                high/low that liquidity is expected to rest beyond.
        """
        self.swing_lookback = swing_lookback

    def _evaluate(self, window, sweep, confirmation):
        swing_low = window["Low"].min()
        swing_high = window["High"].max()

        swept_low = sweep["Low"] < swing_low
        swept_high = sweep["High"] > swing_high

        if swept_low and not swept_high:
            direction = "bullish"
            valid = confirmation["Low"] >= sweep["Low"] and confirmation["Close"] > sweep["Close"]
            swept_level = swing_low
        elif swept_high and not swept_low:
            direction = "bearish"
            valid = confirmation["High"] <= sweep["High"] and confirmation["Close"] < sweep["Close"]
            swept_level = swing_high
        else:
            return None

        if not valid:
            return None

        return {
            "direction": direction,
            "swept_level": swept_level,
            "sweep_low": sweep["Low"],
            "sweep_high": sweep["High"],
        }

    def calculate(self, df):
        """Batch mode: For backtesting on full historical data"""
        matches = [None] * len(df)
        for i in range(self.swing_lookback, len(df) - 1):
            window = df.iloc[i - self.swing_lookback : i]
            sweep = df.iloc[i]
            confirmation = df.iloc[i + 1]
            matches[i] = self._evaluate(window, sweep, confirmation)
        return pd.Series(matches, index=df.index, name="liquidity_sweep")

    def update(self, candles):
        """Streaming mode: For paper & live trading, needs the swing window plus sweep and confirmation candles"""
        if len(candles) < self.swing_lookback + 2:
            return None
        recent = pd.DataFrame(list(candles[-(self.swing_lookback + 2):]))
        window = recent.iloc[: self.swing_lookback]
        sweep = recent.iloc[-2]
        confirmation = recent.iloc[-1]
        return self._evaluate(window, sweep, confirmation)


class MarketStructureShift(Pattern):
    """
    A Change of Character (CHoCH) marks the point where an established
    trend breaks: in an uptrend, a close below the most recent swing low;
    in a downtrend, a close above the most recent swing high. ICT traders
    treat this level as confirmation that the trend has shifted.
    """
    def __init__(self, swing_lookback=10):
        """
        Parameters:
            swing_lookback (int): Candles used to establish the swing
                high/low that must be broken to confirm the shift.
        """
        self.swing_lookback = swing_lookback

    def _evaluate(self, window, candle):
        swing_low = window["Low"].min()
        swing_high = window["High"].max()

        if candle["Close"] < swing_low:
            return {"direction": "bearish", "shift_level": swing_low}
        elif candle["Close"] > swing_high:
            return {"direction": "bullish", "shift_level": swing_high}
        return None

    def calculate(self, df):
        """Batch mode: For backtesting on full historical data"""
        matches = [None] * len(df)
        for i in range(self.swing_lookback, len(df)):
            window = df.iloc[i - self.swing_lookback : i]
            candle = df.iloc[i]
            matches[i] = self._evaluate(window, candle)
        return pd.Series(matches, index=df.index, name="market_structure_shift")

    def update(self, candles):
        """Streaming mode: For paper & live trading, needs the swing window plus the latest candle"""
        if len(candles) < self.swing_lookback + 1:
            return None
        recent = pd.DataFrame(list(candles[-(self.swing_lookback + 1):]))
        window = recent.iloc[:-1]
        candle = recent.iloc[-1]
        return self._evaluate(window, candle)
