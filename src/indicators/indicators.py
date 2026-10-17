"""
indicators.py
Technical indicators calculated from a ticker's candles
"""

#Third Party Imports
import pandas as pd
import numpy as np

#Local Imports
from data.market_calendar import NEW_YORK

def _check_window(window, name: str) -> None:
    """Raise ValueError unless window is a whole number of 1 or more"""
    if (not isinstance(window, int) 
        or isinstance(window, bool)
        or window < 1):
        raise ValueError(f"Invalid {name} {window!r}. Expected a whole number of 1 or more")

def _ema(values: pd.Series, window: int) -> pd.Series:
    """Return the EMA of values, NaN until window values exist"""
    return values.ewm(span=window, adjust=False, min_periods=window).mean()

def _sma(values: pd.Series, window: int) -> pd.Series:
    """Return the rolling mean of values, NaN until window values exist"""
    return values.rolling(window=window).mean()

def calculate_sma(candles: pd.DataFrame, window: int) -> pd.Series:
    """Return the simple moving average of each candle's close
    
    Parameters: 
        candles (pd.DataFrame): Closed candles, oldest first, with a close column
        window (int): Number of candles in each average
    
    Returns:
        A Series on the candles' index; the first window - 1 values are NaN

    Raises:
        ValueError if window isn't a whole number of 1 or more
    """
    _check_window(window=window, name="window")

    sma = _sma(values=candles["close"], window=window)
    return sma

def calculate_ema(candles: pd.DataFrame, window: int) -> pd.Series:
    """Return the exponential moving average of each candle's close
    
    Parameters: 
        candles (pd.DataFrame): Closed candles, oldest first, with a close column
        window (int): Smoothing span; the newest close is weighted 2 / (window + 1)
    
    Returns:
        A Series on the candles' index; the first window - 1 values are NaN

    Raises:
        ValueError if window isn't a whole number of 1 or more
    """
    _check_window(window=window, name="window")

    ema = _ema(values=candles["close"], window=window)
    return ema

def calculate_rsi(candles: pd.DataFrame, window: int) -> pd.Series:
    """Return the relative strength index (0 to 100) of each candle's close

    Uses Wilder's smoothing. 100 means only gains over the window, 0 only losses,
    and a flat price returns 50.

    Parameters:
        candles (pd.DataFrame): Closed candles, oldest first, with a close column
        window (int): Smoothing length; the newest change is weighted 1 / window

    Returns:
        A Series on the candles' index; the first window values are NaN

    Raises:
        ValueError if window isn't a whole number of 1 or more
    """
    _check_window(window=window, name="window")

    delta = candles['close'].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rsi = 100 - (100 / (1 + avg_gain / avg_loss))
    rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50)
    return rsi

def calculate_macd(candles: pd.DataFrame, fast_window: int, slow_window: int, signal_window: int) -> pd.DataFrame:
    """Return the MACD line, its signal line and the histogram for each candle

    Parameters:
        candles (pd.DataFrame): Closed candles, oldest first, with a close column
        fast_window (int): Span of the fast EMA; must be less than slow_window
        slow_window (int): Span of the slow EMA
        signal_window (int): Span of the EMA that smooths the macd line

    Returns:
        A DataFrame with columns macd, signal and histogram on the candles' index;
        macd is NaN for the first slow_window - 1 rows, signal and histogram for the
        first slow_window + signal_window - 2 rows

    Raises:
        ValueError if any window isn't a whole number of 1 or more,
        or if fast_window isn't less than slow_window
    """
    _check_window(window=fast_window, name="fast_window")
    _check_window(window=slow_window, name="slow_window")
    _check_window(window=signal_window, name="signal_window")
    if fast_window >= slow_window:
        raise ValueError(f"The fast_window {fast_window!r} must be less than the slow_window {slow_window!r}")
    macd = _ema(candles["close"], fast_window) - _ema(candles["close"], slow_window)
    signal = _ema(macd, signal_window)
    histogram = macd - signal
    return pd.DataFrame({"macd": macd, "signal": signal, "histogram": histogram})

def calculate_average_volume(candles: pd.DataFrame, window: int) -> pd.Series:
    """Return the average volume of each candle's window, including that candle

    To compare a candle with the candles before it (a volume spike), shift the result by one:
    average.shift(1).iloc[-1] is the average of the window that ended one candle earlier.

    Parameters:
        candles (pd.DataFrame): Closed candles, oldest first, with a volume column
        window (int): Number of candles in each average

    Returns:
        A Series on the candles' index; the first window - 1 values are NaN

    Raises:
        ValueError if window isn't a whole number of 1 or more
    """
    _check_window(window=window, name="window")
    avg_volume = _sma(values=candles["volume"], window=window)
    return avg_volume

def calculate_volatility(candles: pd.DataFrame, window: int) -> pd.Series:
    """Return the historical volatility of each candle's close

    Parameters:
        candles (pd.DataFrame): Closed candles, oldest first, with a close column
        window (int): Number of log returns in each standard deviation; at least 2

    Returns:
        A Series on the candles' index; the first window values are NaN

    Raises:
        ValueError if window isn't a whole number of 2 or more
    """
    _check_window(window=window, name="window")
    if window < 2:
        raise ValueError(f"Invalid window {window!r}. Expected a whole number of 2 or more")

    log_return = np.log(candles["close"] / candles["close"].shift(1))
    volatilitiy = log_return.rolling(window=window).std()
    return volatilitiy

def calculate_vwap(candles: pd.DataFrame) -> pd.Series:
    """Return the volume-weighted average price of each New York trading day so far

    Parameters:
        candles (pd.DataFrame): Closed candles, oldest first, with timestamp (UTC),
            high, low, close and volume columns

    Returns:
        A Series on the candles' index; NaN while the day's volume so far is 0
    """
    typical = (candles["high"] + candles["low"] + candles["close"]) / 3
    price_volume = typical * candles["volume"]
    day = candles["timestamp"].dt.tz_convert(NEW_YORK).dt.date
    running_price_volume = price_volume.groupby(day).cumsum()
    running_volume = candles["volume"].groupby(day).cumsum()
    vwap = running_price_volume / running_volume
    return vwap