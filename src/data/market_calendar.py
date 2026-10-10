"""
market_calendar.py
Trading days with their real open and close times, from Alpaca's market calendar
"""

#Standard Library
from datetime import date

#Third Party Libraries
from alpaca.trading.requests import GetCalendarRequest
import pandas as pd

NEW_YORK = "America/New_York"
SESSION_TIME_FRAMES = ("1Day", "1Week", "1Month")

def get_calendar(trading_client, start: date, end: date) -> dict:
    """Return the trading days between two dates with their open and close times

    One API call; fetch once a day, not every cycle. Days the market is closed
    (weekends, holidays) aren't in the result. end must reach at least ~35 days past
    today, or the current week's and month's candles look closed too early.

    Parameters:
        trading_client (TradingClient): Alpaca trading client from alpaca_client.py
        start (date): First date to include
        end (date): Last date to include

    Returns:
        {trading date: {"open": UTC Timestamp, "close": UTC Timestamp}}
    """
    calendar = {}
    request = GetCalendarRequest(start=start, end=end)
    days = trading_client.get_calendar(request)
    for day in days:
        open_time = pd.Timestamp(day.open).tz_localize(NEW_YORK).tz_convert("UTC")
        close_time = pd.Timestamp(day.close).tz_localize(NEW_YORK).tz_convert("UTC")
        calendar[day.date] = {"open": open_time, "close": close_time}
    return calendar

def last_trading_day(candle_start: date, time_frame: str, calendar: dict) -> date:
    """Return the last trading day inside a session candle's period

    1Day: the day itself. 1Week: the last trading day Monday-Sunday of that week.
    1Month: the last trading day of that month.

    Parameters:
        candle_start (date): The candle's New York date (Alpaca stamps midnight New York)
        time_frame (str): One of SESSION_TIME_FRAMES
        calendar (dict): Trading days from get_calendar

    Returns:
        The last trading date of the candle's period

    Raises:
        ValueError if time_frame isn't in SESSION_TIME_FRAMES
    """
    if time_frame == "1Day":
        return candle_start
    if time_frame == "1Week":
        same_period = [d for d in calendar if d.isocalendar()[:2] == candle_start.isocalendar()[:2]]
    elif time_frame == "1Month":
        same_period = [d for d in calendar if (d.year, d.month) == (candle_start.year, candle_start.month)]
    else:
        raise ValueError(f"Unknown session time frame {time_frame!r}. Expected one of {list(SESSION_TIME_FRAMES)}")
    return max(same_period)

def trading_days_between(start: date, end: date, calendar: dict) -> list:
    """Return the trading dates from start to end, both included

    Parameters:
        start (date): First date to include
        end (date): Last date to include
        calendar (dict): Trading days from get_calendar

    Returns:
        A list of dates, oldest first
    """
    return sorted([d for d in calendar if start <= d <= end])
