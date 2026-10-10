"""
time_frames.py
Time frame helpers and the data clock (now minus the plan's lag)
"""

#Standard Library
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

#Third Party Libraries
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

#Local Imports
from data.market_calendar import NEW_YORK, last_trading_day

# Keys are the strings saved in every time_frame column.
# kind: "intraday" = fetched as is, "built" = made from `source` candles starting at the open,
#       "session" = Alpaca's daily / weekly / monthly candles, closed by the trading calendar.
# minutes: candle length; for session kinds, approximate trading minutes, used only to compare time frames.
TIME_FRAMES = {
    "1Min":   {"kind": "intraday", "minutes": 1,    "alpaca": TimeFrame(1, TimeFrameUnit.Minute)},
    "5Min":   {"kind": "intraday", "minutes": 5,    "alpaca": TimeFrame(5, TimeFrameUnit.Minute)},
    "15Min":  {"kind": "intraday", "minutes": 15,   "alpaca": TimeFrame(15, TimeFrameUnit.Minute)},
    "30Min":  {"kind": "intraday", "minutes": 30,   "alpaca": TimeFrame(30, TimeFrameUnit.Minute)},
    "1Hour":  {"kind": "built",    "minutes": 60,   "source": "30Min"},
    "4Hour":  {"kind": "built",    "minutes": 240,  "source": "30Min"},
    "1Day":   {"kind": "session",  "minutes": 390,  "alpaca": TimeFrame(1, TimeFrameUnit.Day)},
    "1Week":  {"kind": "session",  "minutes": 1950, "alpaca": TimeFrame(1, TimeFrameUnit.Week)},
    "1Month": {"kind": "session",  "minutes": 8190, "alpaca": TimeFrame(1, TimeFrameUnit.Month)},
}

def _spec(time_frame: str) -> dict:
    """Return the TIME_FRAMES entry, or raise ValueError for an unknown time frame"""
    if time_frame not in TIME_FRAMES:
        raise ValueError(f"Unknown time frame {time_frame!r}. Expected one of {list(TIME_FRAMES)}")
    return TIME_FRAMES[time_frame]

def to_minutes(time_frame: str) -> int:
    """Return the length of one candle in minutes

    Session kinds return approximate trading minutes, only for comparing time frames.

    Parameters:
        time_frame (str): A key in TIME_FRAMES, e.g. "15Min"

    Returns:
        The candle length as an int, e.g. 15

    Raises:
        ValueError if time_frame isn't in TIME_FRAMES
    """
    return _spec(time_frame)["minutes"]

def kind(time_frame: str) -> str:
    """Return the kind of a time frame

    Parameters:
        time_frame (str): A key in TIME_FRAMES

    Returns:
        "intraday", "built" or "session"

    Raises:
        ValueError if time_frame isn't in TIME_FRAMES
    """
    return _spec(time_frame)["kind"]

def fetch_as(time_frame: str) -> str:
    """Return the time frame to request from Alpaca

    Built kinds are made from their source candles, so several time frames can share one request.

    Parameters:
        time_frame (str): A key in TIME_FRAMES

    Returns:
        The source time frame for built kinds, otherwise time_frame itself,
        e.g. "4Hour" -> "30Min", "15Min" -> "15Min"

    Raises:
        ValueError if time_frame isn't in TIME_FRAMES
    """
    if kind(time_frame) == "built":
        return TIME_FRAMES[time_frame]["source"]
    return time_frame


def to_alpaca(time_frame: str) -> TimeFrame:
    """Return the alpaca-py TimeFrame to request

    Parameters:
        time_frame (str): A key in TIME_FRAMES

    Returns:
        The TimeFrame of fetch_as(time_frame), e.g. "4Hour" -> TimeFrame(30, TimeFrameUnit.Minute)

    Raises:
        ValueError if time_frame isn't in TIME_FRAMES
    """
    return _spec(fetch_as(time_frame))["alpaca"]

def is_allowed(time_frame: str, profile: dict) -> bool:
    """Check whether the market data plan allows a time frame

    Parameters:
        time_frame (str): A key in TIME_FRAMES
        profile (dict): The market data profile from get_market_data_profile

    Returns:
        True if the time frame is at least the profile's min_time_frame_minutes
    """
    if to_minutes(time_frame) >= profile["min_time_frame_minutes"]:
        return True
    return False

def data_now(now: datetime, profile: dict) -> datetime:
    """Return the newest moment the market data plan lets us see

    Parameters:
        now (datetime): The current time in UTC
        profile (dict): The market data profile from get_market_data_profile

    Returns:
        now minus the profile's lag_minutes, in UTC
    """
    return now - timedelta(minutes=profile["lag_minutes"])

def candle_end(candle_start: datetime, time_frame: str, calendar: dict) -> datetime:
    """Return when a candle finishes

    intraday: candle_start + length.
    built: the earlier of candle_start + length and that day's close
    (the last 4Hour candle is 13:30-16:00, and early-close days end at 13:00).
    session: the close of the last trading day in the candle's day, week or month.

    Parameters:
        candle_start (datetime): The candle's start in UTC, as Alpaca stamps it
        time_frame (str): A key in TIME_FRAMES
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        The candle's end in UTC
    """
    length = timedelta(minutes=to_minutes(time_frame))
    day = candle_start.astimezone(ZoneInfo(NEW_YORK)).date()

    if kind(time_frame) == "intraday":
        return candle_start + length
    if kind(time_frame) == "built":
        close = calendar[day]["close"]
        return min(candle_start + length, close)

    last_day = last_trading_day(day, time_frame, calendar)
    return calendar[last_day]["close"]

def is_closed(candle_start: datetime, time_frame: str, as_of: datetime, calendar: dict) -> bool:
    """Check whether a candle has finished

    Parameters:
        candle_start (datetime): The candle's start in UTC, as Alpaca stamps it
        time_frame (str): A key in TIME_FRAMES
        as_of (datetime): The data clock from data_now, in UTC
        calendar (dict): Trading days from market_calendar.get_calendar

    Returns:
        True if the candle ended at or before as_of
    """
    return candle_end(candle_start, time_frame, calendar) <= as_of
