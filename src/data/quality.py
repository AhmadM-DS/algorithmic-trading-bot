"""
quality.py
Data quality checks on each ticker's candles every cycle (DATA-8)
"""

#Standard Library
from datetime import datetime, date

#Third Party Libraries
import pandas as pd

#Local Imports
from data.time_frames import kind, to_minutes, candle_end
from data.market_calendar import NEW_YORK, trading_days_between
from data.candles import COLUMNS

def period_key(ts: pd.Timestamp, time_frame: str):
    """Return what identifies a candle when comparing expected and present candles

    Alpaca's session timestamps can vary (a month can be stamped on a Saturday),
    so session kinds compare by day, (year, ISO week) or (year, month) instead of exact time.

    Parameters:
        ts (Timestamp): A candle start in UTC
        time_frame (str): A key in TIME_FRAMES

    Returns:
        ts for intraday and built kinds; a date, (year, week) or (year, month) for session kinds
    """
    if kind(time_frame) != "session":
        return ts
    day = ts.tz_convert(NEW_YORK).date()
    if time_frame == "1Day":
        return day
    if time_frame == "1Week":
        return day.isocalendar()[:2]
    return (day.year, day.month)

def expected_starts(time_frame: str, first_day: date, last_day: date, calendar: dict) -> list:
    """Return every candle start that should exist between two trading days

    Intraday and built kinds: every step from each day's open up to, not including, its close.
    Session kinds: midnight New York of each trading day (compare them with period_key).

    Parameters:
        time_frame (str): A key in TIME_FRAMES
        first_day (date): First New York date to include
        last_day (date): Last New York date to include
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        A list of UTC Timestamps, oldest first
    """
    starts = []
    for day in trading_days_between(first_day, last_day, calendar):
        if kind(time_frame) == "session":
            starts.append(pd.Timestamp(day).tz_localize(NEW_YORK).tz_convert("UTC"))
        else:
            starts.extend(pd.date_range(calendar[day]["open"], calendar[day]["close"],
                                        freq=pd.Timedelta(minutes=to_minutes(time_frame)), inclusive="left"))
    return starts

def count_missing(df: pd.DataFrame, time_frame: str, calendar: dict) -> int:
    """Count candles missing between the first and last candle

    Weekends, holidays and early closes come from the calendar, so they never count.
    Alpaca skips a candle when nothing traded, so thin tickers can have real gaps.

    Parameters:
        df (DataFrame): One ticker's candles with COLUMNS
        time_frame (str): A key in TIME_FRAMES
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        Expected candles minus present candles; 0 for an empty table
    """
    if df.empty:
        return 0
    first, last = df["timestamp"].min(), df["timestamp"].max()
    expected = {period_key(ts, time_frame)
                for ts in expected_starts(time_frame, first.tz_convert(NEW_YORK).date(), last.tz_convert(NEW_YORK).date(), calendar)}
    expected = {k for k in expected if period_key(first, time_frame) <= k <= period_key(last, time_frame)}
    present = {period_key(ts, time_frame) for ts in df["timestamp"]}
    return len(expected - present)

def count_duplicates(df: pd.DataFrame) -> int:
    """Count candles that share a timestamp with an earlier candle

    Parameters:
        df (DataFrame): One ticker's candles with COLUMNS

    Returns:
        The number of repeated timestamps
    """
    return int(df["timestamp"].duplicated().sum())

def count_zero_volume(df: pd.DataFrame) -> int:
    """Count candles with zero volume

    Parameters:
        df (DataFrame): One ticker's candles with COLUMNS

    Returns:
        The number of rows where volume is 0 (NaN isn't counted here)
    """
    return int((df["volume"] == 0).sum())

def count_empty(df: pd.DataFrame) -> int:
    """Count candles with any empty (NaN) value

    Parameters:
        df (DataFrame): One ticker's candles with COLUMNS

    Returns:
        The number of rows with at least one NaN
    """
    return int(df[COLUMNS].isna().any(axis=1).sum())

def stale_timestamp(df: pd.DataFrame, time_frame: str, as_of: datetime, stale_after_candles: int, calendar: dict):
    """Return the last candle's time if too many newer closed candles are missing

    Counts the candles that should exist after the last one and have closed by as_of,
    using the calendar, so Friday's last candle isn't stale on Monday morning.
    as_of is the data clock, so the plan's normal lag isn't stale.

    Parameters:
        df (DataFrame): One ticker's candles with COLUMNS
        time_frame (str): A key in TIME_FRAMES
        as_of (datetime): The data clock from data_now, in UTC
        stale_after_candles (int): How many missing newer candles are allowed
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        The last candle's start (UTC) if stale, otherwise None; None for an empty table
    """
    if df.empty:
        return None
    last = df["timestamp"].max()
    newer = {period_key(ts, time_frame)
             for ts in expected_starts(time_frame, last.tz_convert(NEW_YORK).date(), as_of.tz_convert(NEW_YORK).date(), calendar)
             if period_key(ts, time_frame) > period_key(last, time_frame) and candle_end(ts, time_frame, calendar) <= as_of}
    return last if len(newer) > stale_after_candles else None

def lag_seconds(df: pd.DataFrame, time_frame: str, now: datetime, calendar: dict):
    """Return the seconds between the last candle's end and the real now

    Includes the plan's lag on purpose; it's saved with market_data_plan so the two read together.

    Parameters:
        df (DataFrame): One ticker's candles with COLUMNS
        time_frame (str): A key in TIME_FRAMES
        now (datetime): The current time in UTC
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        Whole seconds as an int; None for an empty table
    """
    if df.empty:
        return None
    return int((now - candle_end(df["timestamp"].max(), time_frame, calendar)).total_seconds())

def grade(row: dict, thresholds: dict, has_candles: bool) -> str:
    """Return the data_health status for one ticker's checks

    bad: no candles, duplicates, empty values or stale. warn: missing or zero-volume
    candles over their thresholds. ok: everything else.

    Parameters:
        row (dict): The counts from check_candles
        thresholds (dict): DATA_HEALTH_THRESHOLDS from constants.py
        has_candles (bool): False if the ticker's table is empty

    Returns:
        "ok", "warn" or "bad"
    """
    if not has_candles or row["duplicates"] or row["empty_values"] or row["stale_last_timestamp"] is not None:
        return "bad"
    if row["missing_candles"] > thresholds["max_missing_candles"] or row["zero_volume"] > thresholds["max_zero_volume"]:
        return "warn"
    return "ok"

def check_candles(df: pd.DataFrame, time_frame: str, now: datetime, as_of: datetime, profile_name: str, thresholds: dict, calendar: dict) -> dict:
    """Return one data_health row (without ticker_id) for one ticker

    Parameters:
        df (DataFrame): One ticker's candles from get_candles
        time_frame (str): A key in TIME_FRAMES
        now (datetime): The current time in UTC (saved as checked_at)
        as_of (datetime): The data clock from data_now, in UTC
        profile_name (str): MARKET_DATA_PLAN, saved as market_data_plan
        thresholds (dict): DATA_HEALTH_THRESHOLDS from constants.py
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        A dict whose keys match the data_health columns
    """
    row = {
        "checked_at": now,
        "time_frame": time_frame,
        "missing_candles": count_missing(df, time_frame, calendar),
        "stale_last_timestamp": stale_timestamp(df, time_frame, as_of, thresholds["stale_after_candles"], calendar),
        "zero_volume": count_zero_volume(df),
        "duplicates": count_duplicates(df),
        "empty_values": count_empty(df),
        "lag_seconds": lag_seconds(df, time_frame, now, calendar),
        "market_data_plan": profile_name,
    }
    row["status"] = grade(row, thresholds, not df.empty)
    return row

def should_save(status: str, save_mode: str) -> bool:
    """Check whether a data_health row should be saved

    Parameters:
        status (str): "ok", "warn" or "bad"
        save_mode (str): DATA_HEALTH_SAVE: "failures" (warn / bad only) or "all"

    Returns:
        True if the row should be saved

    Raises:
        ValueError if save_mode isn't "failures" or "all"
    """
    if save_mode not in ("failures", "all"):
        raise ValueError(f"Unknown DATA_HEALTH_SAVE {save_mode!r}. Expected one of ['failures', 'all']")
    return save_mode == "all" or status != "ok"
