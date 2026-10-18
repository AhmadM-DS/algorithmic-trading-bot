"""
test_indicators.py
Unit tests for the indicator functions
"""

#Standard Library
import math

#Third Party Libraries
import pytest
import re

#Local Imports
from indicators.indicators import (
    _check_window, calculate_sma, calculate_ema, 
    calculate_rsi, calculate_macd, calculate_average_volume,
    calculate_volatility, calculate_vwap,
    candles_needed)
import pandas as pd
import pandas.testing as pdt

CANDLES = pd.DataFrame({
    "close": [10, 20, 30, 40, 50, 60],
    "volume": [100, 200, 300, 400, 500, 600]
})

VWAP_CANDLES = pd.DataFrame({
    "timestamp": pd.to_datetime(["2026-10-13 13:30", "2026-10-13 13:45",
                                 "2026-10-14 13:30", "2026-10-14 13:45"], utc=True),
    "high":   [12, 15, 21, 24],
    "low":    [8,  9, 15, 18],
    "close":  [10, 12, 18, 21],
    "volume": [100, 300, 200, 200],
})


#fixture
WINDOW_INDICATORS = [calculate_sma, calculate_ema, 
                    calculate_rsi, calculate_average_volume,
                    calculate_volatility]
@pytest.fixture(params=WINDOW_INDICATORS, ids=lambda f: f.__name__)
def indicator(request):
    """Provide each single-window indicator function in turn"""
    return request.param


def test_check_window_accepts_positive_int():
    """Accept a whole number of 1 or more"""
    _check_window(14, "accepted_window")

@pytest.mark.parametrize("bad_window", [0, -1])
def test_check_window_rejects_zero_and_negative(bad_window):
    """Reject a window below 1"""
    with pytest.raises(ValueError, match="window"):
        _check_window(bad_window, "window")

def test_check_window_rejects_float():
    """Reject a float window"""
    with pytest.raises(ValueError, match=re.escape("Invalid window 2.5")):
        _check_window(2.5, "window")

def test_check_window_rejects_bool():
    """Reject a bool window, even though bool is a kind of int"""
    with pytest.raises(ValueError, match="Invalid slow_window"):
        _check_window(True, "slow_window")

#-------sma tests-------------
def test_sma_matches_hand_calculation():
    """Match hand-calculated SMA values"""
    sma = calculate_sma(CANDLES, 3)
    expected_sma = pd.Series([None, None, 20, 30, 40, 50], dtype='float64', name='close')
    pdt.assert_series_equal(sma, expected_sma)

#-------ema tests-------------
def test_ema_matches_hand_calculation():
    """Match hand-calculated EMA values"""
    ema = calculate_ema(CANDLES, 3)
    expected_ema = pd.Series([None, None, 22.5, 31.25, 40.625, 50.3125], dtype='float64', name='close')
    pdt.assert_series_equal(ema, expected_ema)

#-------rsi tests-------------
def test_rsi_matches_hand_calculation():
    """Match hand-calculated RSI values from Wilder's averages"""
    rsi = calculate_rsi(pd.DataFrame({'close': [10, 5, 30, 2, 47, 0]}), 2)
    expected_rsi = pd.Series([None, None,
                              100 - 100 / (1 + 12.5 / 2.5),
                              100 - 100 / (1 + 6.25 / 15.25),
                              100 - 100 / (1 + 25.625 / 7.625),
                              100 - 100 / (1 + 12.8125 / 27.3125)], dtype='float64', name='close')
    pdt.assert_series_equal(rsi, expected_rsi)

def test_rsi_is_100_when_price_only_rises():
    """Return 100 when the price only rises"""
    rsi = calculate_rsi(CANDLES, 2)
    expected_rsi = pd.Series([None, None, 100, 100, 100, 100], dtype='float64', name='close')
    pdt.assert_series_equal(rsi, expected_rsi)

def test_rsi_is_50_when_price_is_flat():
    """Return 50 when the price is flat, and keep the warm-up NaN"""
    rsi = calculate_rsi(pd.DataFrame({'close': [10, 10, 10, 10, 10, 10]}), 2)
    expected_rsi = pd.Series([None, None, 50, 50, 50, 50], dtype='float64', name='close')
    pdt.assert_series_equal(rsi, expected_rsi)

#-------combined ema and sma tests-------------
def test_indicator_is_nan_until_window_is_full(indicator):
    """Return NaN for every candle before the window is full"""
    result = indicator(CANDLES, 3)
    assert result.iloc[:3 - 1].isna().all()

def test_indicator_keeps_candle_index(indicator):
    """Return one value per candle on the candles' index"""
    result = indicator(CANDLES, 3)
    assert result.index.equals(CANDLES.index)

def test_indicator_does_not_look_ahead(indicator):
    """Keep earlier values unchanged when a new candle arrives"""
    result = indicator(CANDLES, 3)
    result_2 = indicator(CANDLES.iloc[:4], 3)
    pdt.assert_series_equal(result.iloc[:4], result_2)

def test_indicator_rejects_bad_window(indicator):
    """Reject an invalid window"""
    with pytest.raises(ValueError, match="Invalid window 0"):
        indicator(CANDLES, 0)

#-------macd tests------------
def test_macd_matches_hand_calculation():
    """Match hand-calculated macd, signal and histogram values"""
    result = calculate_macd(CANDLES, 1, 3, 3)
    expected_result = pd.DataFrame({
        "macd": [None, None, 7.5, 8.75, 9.375, 9.6875],
        "signal": [None, None, None, None, 8.75, 9.21875],
        "histogram": [None, None, None, None, 0.625, 0.46875]
    })
    pdt.assert_frame_equal(result, expected_result)

@pytest.mark.parametrize("windows", [(26, 12, 9), (26, 26, 9)])
def test_macd_rejects_fast_not_below_slow(windows):
    """Reject a fast_window that isn't less than slow_window"""
    with pytest.raises(ValueError, match="less than the slow_window"):
        calculate_macd(CANDLES, *windows)

def test_macd_names_the_bad_window():
    """Name the invalid window in the error message"""
    with pytest.raises(ValueError, match="fast_window"):
        calculate_macd(CANDLES, -1, 2, 3)
    with pytest.raises(ValueError, match="slow_window"):
            calculate_macd(CANDLES, 1, -2, 3)
    with pytest.raises(ValueError, match="signal_window"):
            calculate_macd(CANDLES, 1, 2, -3)

def test_macd_does_not_look_ahead():
    """Keep earlier values unchanged when a new candle arrives"""
    result = calculate_macd(CANDLES, 1, 3, 3)
    result_2 = calculate_macd(CANDLES.iloc[:4], 1, 3, 3)
    pdt.assert_frame_equal(result.iloc[:4], result_2)

def test_macd_keeps_candle_index():
    """Return one row per candle on the candles' index"""
    result = calculate_macd(CANDLES, 1, 3, 3)
    assert result.index.equals(CANDLES.index)

#------average volume tests---------
def test_average_volume_matches_hand_calculation():
    """Match hand-calculated average volume values"""
    result = calculate_average_volume(CANDLES, 3)
    result_2 = pd.Series([None, None, 200, 300, 400, 500], dtype="float64", name="volume")
    pdt.assert_series_equal(result, result_2)

#-------volatility tests---------
def test_volatility_matches_hand_calculation():
    """Match the hand-calculated standard deviation of alternating log returns"""
    temp_candles = pd.DataFrame({"close": [100, 200, 100, 200, 100, 200]})
    result = calculate_volatility(temp_candles, 2)
    r = math.log(2)
    expected = math.sqrt((r**2 + r**2) / (2 - 1))
    result_2 = pd.Series([None, None, expected, expected, expected, expected], dtype="float64", name="close")
    pdt.assert_series_equal(result, result_2)

def test_volatility_is_zero_when_price_is_flat():
    """Return 0 when the price never moves"""
    temp_candles = pd.DataFrame({"close": [100, 100, 100, 100, 100, 100]})
    result = calculate_volatility(temp_candles, 2)
    result_2 = pd.Series([None, None, 0, 0, 0, 0], dtype="float64", name="close")
    pdt.assert_series_equal(result, result_2)

def test_volatility_rejects_window_of_one():
    """Reject a window of 1, which can never produce a standard deviation"""
    with pytest.raises(ValueError, match="2 or more"):
        calculate_volatility(CANDLES, 1)

#--------vwap tests----------
def test_vwap_matches_hand_calculation():
    """Match hand-calculated VWAP values from each day's running totals"""
    result = calculate_vwap(VWAP_CANDLES)
    expected = pd.Series([
        (10 * 100) / 100,
        (10 * 100 + 12 * 300) / (100 + 300),
        (18 * 200) / (200),
        (18 * 200 + 21 * 200) / (200 + 200)
    ])
    pdt.assert_series_equal(result, expected)

def test_vwap_resets_each_new_york_day():
    """Start each New York day from that day's first candle"""
    result = calculate_vwap(VWAP_CANDLES)
    assert result.iloc[2] == pytest.approx((21 + 15 + 18) / 3)

def test_vwap_does_not_look_ahead():
    """Keep earlier values unchanged when a new candle arrives"""
    result = calculate_vwap(VWAP_CANDLES)
    result_2 = calculate_vwap(VWAP_CANDLES.iloc[:3])
    pdt.assert_series_equal(result.iloc[:3], result_2)

def test_vwap_keeps_candle_index():
    """Return one value per candle on the candles' index"""
    vwap = calculate_vwap(VWAP_CANDLES)
    assert vwap.index.equals(VWAP_CANDLES.index)

#------candles tests----------
@pytest.mark.parametrize("indicator, expected", [
    (("sma", 20), 20),
    (("average_volume", 10), 10),
    (("volatility", 20), 21),
    (("ema", 14), 34),
    (("ema", 200), 462),
    (("rsi", 14), 65),
    (("macd", 12, 26, 9), 82),
    (("ema", 1), 1),
])

def test_candles_needed_matches_known_counts(indicator, expected):
    """Return the known candle count for each indicator at a 1% tolerance"""
    assert candles_needed(indicator, tolerance=0.01) == expected

def test_candles_needed_never_below_window():
    """Return at least the window when a loose tolerance needs fewer candles"""
    assert candles_needed(("ema", 14), tolerance=0.9) == 14

def test_ema_seed_weight_falls_to_tolerance_at_candles_needed():
    """Match pandas: the seed's weight is within tolerance at the last needed candle, not one before"""
    needed = candles_needed(("ema", 14), tolerance=0.01)
    impulse = pd.Series([1.0] + [0.0] * 600)

    seed_weight = impulse.ewm(span=14, adjust=False, min_periods=14).mean()

    assert seed_weight.iloc[needed - 1] <= 0.01
    assert seed_weight.iloc[needed - 2] > 0.01

@pytest.mark.parametrize("indicator, tolerance", [
    (("vwap",), 0.01),
    (("macd", 12), 0.01),
    (("ema", 0), 0.01),
    (("macd", 26, 12, 9), 0.01),
    (("ema", 14), 0),
    (("ema", 14), 1),
])
def test_candles_needed_rejects_bad_input(indicator, tolerance):
    """Raise ValueError for an unknown name, wrong window count, bad window, fast >= slow or bad tolerance"""
    with pytest.raises(ValueError):
        candles_needed(indicator, tolerance=tolerance)
