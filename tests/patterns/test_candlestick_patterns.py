import pytest
import pandas as pd
from patterns.candlestick_patterns import FairValueGap, BullFlagBreakout, FlatTopBreakout, LiquiditySweep, MarketStructureShift

def make_fvg_bullish_df():
    """Row0's High never overlaps Row2's Low -> a clean bullish gap at index 2."""
    return pd.DataFrame({
        "Close": [98, 101, 108],
        "High":  [100, 103, 110],
        "Low":   [95, 99, 106],
    })


def make_fvg_no_gap_df():
    """Overlapping ranges every row -> no gap anywhere."""
    return pd.DataFrame({
        "Close": [98, 99, 100],
        "High":  [100, 101, 102],
        "Low":   [95, 97, 98],
    })


def make_bull_flag_df():
    """
    Rows 0-9: flagpole, close rallies 100 -> 113 (14% gain, above the 8%
    minimum). Rows 10-14: flag, a tight flat consolidation near the top
    (20% pullback, under the 50% max). Row 15: breakout candle closes
    above the flag's high on 1.3x volume (above the 1.2x minimum).
    """
    flagpole_close = [100, 102, 104, 106, 108, 109, 110, 111, 112, 113]
    flagpole_high = [c + 1 for c in flagpole_close]
    flagpole_low = [c - 1 for c in flagpole_close]
    flag_close = [112] * 5
    flag_high = [113] * 5
    flag_low = [111] * 5
    return pd.DataFrame({
        "Close": flagpole_close + flag_close + [115],
        "High": flagpole_high + flag_high + [116],
        "Low": flagpole_low + flag_low + [113.5],
        "Volume": [1000] * 15 + [1300],
    })



def make_flat_top_df():
    """
    Rows 0-9: High touches 100 exactly twice (rows 1 and 4, satisfying
    min_touches=2), staying under it otherwise -> resistance = 100. Row
    10: breakout candle closes above 100 on 1.6x volume (above the 1.5x
    minimum).
    """
    return pd.DataFrame({
        "Close":  [97, 99, 96, 98, 99, 95, 97, 98, 96, 97, 102],
        "High":   [98, 100, 97, 99, 100, 96, 98, 99, 97, 98, 103],
        "Low":    [95, 96, 94, 95, 96, 93, 94, 95, 93, 94, 100.5],
        "Volume": [1000] * 10 + [1600],
    })


def make_flat_top_no_pattern_df():
    """
    Rows 0-9: High only touches 100 once (row 1) -> only 1 touch, below
    the min_touches=2 requirement, so resistance never qualifies as a
    flat top. Row 10 still closes above 100 on high volume, but that
    shouldn't matter -> should still be None.
    """
    return pd.DataFrame({
        "Close":  [97, 99, 95, 96, 94, 95, 93, 94, 92, 93, 102],
        "High":   [98, 100, 96, 97, 95, 96, 94, 95, 93, 94, 103],
        "Low":    [95, 96, 93, 94, 92, 93, 91, 92, 90, 91, 100.5],
        "Volume": [1000] * 10 + [1600],
    })


def make_liquidity_sweep_bullish_df():
    """
    Rows 0-9: establish a swing low of 95 (row 3) and swing high of 105
    (row 5). Row 10 (the sweep): Low dips to 93, under the swing low, but
    High stays under 105 and Close recovers to 98 -> a bullish sweep
    candidate. Row 11 (confirmation): Low stays above the sweep's Low and
    Close is higher than the sweep's Close -> confirms the sweep.
    """
    return pd.DataFrame({
        "Close":  [99, 99, 100, 98, 101, 102, 99, 100, 99, 100, 98, 101],
        "High":   [101, 102, 103, 101, 104, 105, 102, 103, 101, 102, 100, 99],
        "Low":    [97, 96, 98, 95, 97, 98, 96, 97, 98, 99, 93, 94],
        "Volume": [1000] * 12,
    })



def make_market_structure_shift_bullish_df():
    """
    Rows 0-9: same swing window as the liquidity sweep fixture -> swing
    high of 105 (row 5). Row 10: closes at 107, above the swing high ->
    a bullish CHoCH.
    """
    return pd.DataFrame({
        "Close":  [99, 99, 100, 98, 101, 102, 99, 100, 99, 100, 107],
        "High":   [101, 102, 103, 101, 104, 105, 102, 103, 101, 102, 108],
        "Low":    [97, 96, 98, 95, 97, 98, 96, 97, 98, 99, 104],
    })