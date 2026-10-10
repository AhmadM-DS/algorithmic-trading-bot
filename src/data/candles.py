"""
candles.py
Fetch the last N closed candles for many tickers in one Alpaca request
"""

#Standard Library
from datetime import datetime
from zoneinfo import ZoneInfo
import math

#Third Party Libraries
import pandas as pd
from alpaca.data.requests import StockBarsRequest

#Local Imports
from logger import api_log
from data.time_frames import kind, to_alpaca, data_now, is_closed, to_minutes
from data.market_calendar import NEW_YORK
from config.constants import MARKET_OPEN_TIME, PRICE_ADJUSTMENT

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
AGGREGATE = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}

def request_start(as_of: datetime, time_frame: str, lookback: int, calendar: dict) -> pd.Timestamp:
    """Return how far back to ask Alpaca so at least `lookback` candles come back

    Counts back trading days from the calendar, plus one candle's worth as a margin.
    Starts at midnight New York so the first daily candle (stamped midnight) is included.

    Parameters:
        as_of (datetime): The data clock from data_now, in UTC
        time_frame (str): A key in TIME_FRAMES
        lookback (int): Number of closed candles needed
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        The request start in UTC

    Raises:
        ValueError if the calendar doesn't go back far enough
    """
    minutes = to_minutes(time_frame)
    session_minutes = to_minutes("1Day")
    days_needed = math.ceil(lookback * minutes / session_minutes) + math.ceil(minutes / session_minutes)
    as_of_day = as_of.astimezone(ZoneInfo(NEW_YORK)).date()
    days = [d for d in sorted(calendar) if d <= as_of_day]
    if len(days) < days_needed:
        raise ValueError(f"Calendar has {len(days)} trading days up to {as_of_day}; "
                         f"{lookback} {time_frame} candles need {days_needed}")
    return pd.Timestamp(days[-days_needed]).tz_localize(NEW_YORK).tz_convert("UTC")

def build_request(tickers: list, time_frame: str, start: datetime, end: datetime, profile: dict) -> StockBarsRequest:
    """Return one bars request for every ticker

    Parameters:
        tickers (list): Ticker symbols
        time_frame (str): A key in TIME_FRAMES; built kinds request their source
        start (datetime): Request start in UTC
        end (datetime): Request end in UTC
        profile (dict): The market data profile from get_market_data_profile

    Returns:
        A StockBarsRequest with the profile's feed and PRICE_ADJUSTMENT
    """
    return StockBarsRequest(symbol_or_symbols=tickers, timeframe=to_alpaca(time_frame),
                            start=start, end=end, feed=profile["feed"], adjustment=PRICE_ADJUSTMENT)

def regular_hours_only(df: pd.DataFrame, calendar: dict) -> pd.DataFrame:
    """Return the candles that start between that day's open and close

    Uses the calendar's hours, so early closes work. Only for intraday and built kinds:
    session candles start at midnight and would all be dropped.

    Parameters:
        df (DataFrame): One ticker's candles with COLUMNS
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        The kept candles with COLUMNS and a 0..n index
    """
    keep = []
    for ts in df["timestamp"]:
        day = ts.tz_convert(NEW_YORK).date()
        keep.append(day in calendar and calendar[day]["open"] <= ts < calendar[day]["close"])
    return df.loc[keep].reset_index(drop=True)

def split_by_ticker(df: pd.DataFrame, tickers: list) -> dict:
    """Return Alpaca's (symbol, timestamp) table as one table per ticker

    A ticker with no rows gets an empty table with COLUMNS, so the quality check reports it.

    Parameters:
        df (DataFrame): Alpaca's BarSet.df
        tickers (list): The tickers that were requested

    Returns:
        {ticker: DataFrame with COLUMNS, sorted by timestamp, 0..n index}
    """
    result = {}
    for ticker in tickers:
        if df.empty or ticker not in df.index.get_level_values("symbol"):
            result[ticker] = pd.DataFrame(columns=COLUMNS)
        else:
            result[ticker] = (
                df.loc[ticker].reset_index()
                [COLUMNS]
                .sort_values("timestamp")
                .reset_index(drop=True)
            )
    return result

def build_candles(df: pd.DataFrame, time_frame: str) -> pd.DataFrame:
    """Return built-kind candles (1Hour, 4Hour) made from regular-hours 30Min candles

    Bins start at MARKET_OPEN_TIME. Each day is binned separately so the bins don't
    shift when daylight saving time changes.

    Parameters:
        df (DataFrame): One ticker's 30Min candles after regular_hours_only
        time_frame (str): A built key in TIME_FRAMES

    Returns:
        The built candles with COLUMNS, timestamps in UTC
    """
    if df.empty:
        return df
    length = pd.Timedelta(minutes=to_minutes(time_frame))
    offset = pd.Timedelta(f"{MARKET_OPEN_TIME}:00") % length
    ny = df.set_index(df["timestamp"].dt.tz_convert(NEW_YORK))[COLUMNS[1:]]
    built = (
        ny.groupby(ny.index.date, group_keys=False)
        .apply(lambda day: day.resample(length, offset=offset).agg(AGGREGATE))
        .dropna(subset=["open"])
        .reset_index()
    )
    built["timestamp"] = built["timestamp"].dt.tz_convert("UTC")
    return built[COLUMNS]

def regular_hours_volume(daily: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    """Return daily candles with volume replaced by that day's regular-hours volume

    Alpaca's daily volume includes pre-market and after-hours. A day with no 30Min
    candles gets NaN so count_empty flags it. The input table isn't changed.

    Parameters:
        daily (DataFrame): One ticker's 1Day candles
        source (DataFrame): The same ticker's 30Min candles after regular_hours_only

    Returns:
        A copy of daily with the new volume
    """
    result = daily.copy()
    if daily.empty:
        return result
    if source.empty:
        result["volume"] = float("nan")
        return result
    per_day = source.groupby(source["timestamp"].dt.tz_convert(NEW_YORK).dt.date)["volume"].sum()
    result["volume"] = result["timestamp"].dt.tz_convert(NEW_YORK).dt.date.map(per_day)
    return result

def closed_only(df: pd.DataFrame, time_frame: str, as_of: datetime, calendar: dict) -> pd.DataFrame:
    """Return the candles that have finished by as_of

    Parameters:
        df (DataFrame): One ticker's candles with COLUMNS
        time_frame (str): A key in TIME_FRAMES
        as_of (datetime): The data clock from data_now, in UTC
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        The closed candles with COLUMNS and a 0..n index
    """
    keep = [is_closed(ts, time_frame, as_of, calendar) for ts in df["timestamp"]]
    return df.loc[keep].reset_index(drop=True)

def fetch(data_client, tickers: list, time_frame: str, start: datetime, end: datetime, profile: dict) -> dict:
    """Return one table per ticker from a single Alpaca request

    Parameters:
        data_client (StockHistoricalDataClient): Alpaca data client from alpaca_client.py
        tickers (list): Ticker symbols
        time_frame (str): A key in TIME_FRAMES
        start (datetime): Request start in UTC
        end (datetime): Request end in UTC
        profile (dict): The market data profile from get_market_data_profile

    Returns:
        {ticker: DataFrame with COLUMNS}
    """
    request = build_request(tickers, time_frame, start, end, profile)
    return split_by_ticker(data_client.get_stock_bars(request).df, tickers)

def get_candles(data_client, tickers: list, time_frame: str, lookback: int, profile: dict, now: datetime, calendar: dict) -> dict:
    """Return the last `lookback` closed candles per ticker, in memory

    One Alpaca request for all tickers (two for 1Day: the second rebuilds volume).
    Strategies must get a copy (df.copy()) so none can change another's data.
    Alpaca errors aren't caught: the engine decides what a failed fetch means.

    Parameters:
        data_client (StockHistoricalDataClient): Alpaca data client from alpaca_client.py
        tickers (list): Ticker symbols
        time_frame (str): A key in TIME_FRAMES
        lookback (int): Number of closed candles per ticker
        profile (dict): The market data profile from get_market_data_profile
        now (datetime): The current time in UTC
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        {ticker: DataFrame with COLUMNS, oldest first, at most `lookback` rows}

    Raises:
        ValueError if the calendar doesn't go back far enough
    """
    as_of = data_now(now, profile)
    start = request_start(as_of, time_frame, lookback, calendar)
    frames = fetch(data_client, tickers, time_frame, start, as_of, profile)
    if kind(time_frame) != "session":
        frames = {t: regular_hours_only(f, calendar) for t, f in frames.items()}
    if kind(time_frame) == "built":
        frames = {t: build_candles(f, time_frame) for t, f in frames.items()}
    if time_frame == "1Day":
        source = fetch(data_client, tickers, "30Min", start, as_of, profile)
        frames = {t: regular_hours_volume(f, regular_hours_only(source[t], calendar)) for t, f in frames.items()}
    candles = {t: closed_only(f, time_frame, as_of, calendar).tail(lookback).reset_index(drop=True)
               for t, f in frames.items()}
    empty = [t for t, f in candles.items() if f.empty]
    api_log.debug(f"candles: {time_frame} {len(candles)} tickers, "
                  f"{sum(len(f) for f in candles.values())} candles, empty: {empty or 'none'}")
    return candles
