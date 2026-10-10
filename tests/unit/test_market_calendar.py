from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from data.market_calendar import get_calendar, last_trading_day, trading_days_between, SESSION_TIME_FRAMES
from data.time_frames import TIME_FRAMES, candle_end

def utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

def alpaca_day(day, close_hour=16):
    """What Alpaca returns: naive New York times"""
    return SimpleNamespace(date=day,
                           open=datetime(day.year, day.month, day.day, 9, 30),
                           close=datetime(day.year, day.month, day.day, close_hour))

class FakeTradingClient:
    def __init__(self, days):
        self.days = days
        self.requests = []

    def get_calendar(self, request):
        self.requests.append(request)
        return self.days

# Thanksgiving week 2026 plus the following Monday: Nov 26 missing, Nov 27 closes at 13:00
THANKSGIVING_DAYS = [alpaca_day(date(2026, 11, 23)), alpaca_day(date(2026, 11, 24)),
                     alpaca_day(date(2026, 11, 25)), alpaca_day(date(2026, 11, 27), close_hour=13),
                     alpaca_day(date(2026, 11, 30))]

@pytest.fixture
def calendar():
    return get_calendar(FakeTradingClient(THANKSGIVING_DAYS), date(2026, 11, 23), date(2026, 11, 30))

def test_get_calendar_sends_dates():
    client = FakeTradingClient(THANKSGIVING_DAYS)
    get_calendar(client, date(2026, 11, 23), date(2026, 11, 30))
    assert client.requests[0].start == date(2026, 11, 23)
    assert client.requests[0].end == date(2026, 11, 30)

def test_get_calendar_keys_are_trading_days(calendar):
    assert list(calendar) == [d.date for d in THANKSGIVING_DAYS]
    assert date(2026, 11, 26) not in calendar

def test_get_calendar_converts_to_utc(calendar):
    # November is EST (UTC-5)
    assert calendar[date(2026, 11, 24)]["open"] == utc(2026, 11, 24, 14, 30)
    assert calendar[date(2026, 11, 24)]["close"] == utc(2026, 11, 24, 21)
    assert calendar[date(2026, 11, 27)]["close"] == utc(2026, 11, 27, 18)

def test_get_calendar_daylight_saving():
    # July is EDT (UTC-4)
    calendar = get_calendar(FakeTradingClient([alpaca_day(date(2026, 7, 1))]), date(2026, 7, 1), date(2026, 7, 1))
    assert calendar[date(2026, 7, 1)]["close"] == utc(2026, 7, 1, 20)

def test_last_trading_day_day(calendar):
    assert last_trading_day(date(2026, 11, 25), "1Day", calendar) == date(2026, 11, 25)

def test_last_trading_day_week(calendar):
    assert last_trading_day(date(2026, 11, 23), "1Week", calendar) == date(2026, 11, 27)

def test_last_trading_day_month(calendar):
    assert last_trading_day(date(2026, 11, 1), "1Month", calendar) == date(2026, 11, 30)

def test_last_trading_day_unknown_time_frame(calendar):
    with pytest.raises(ValueError, match="15Min"):
        last_trading_day(date(2026, 11, 23), "15Min", calendar)

def test_session_time_frames_match_time_frames_table():
    session = tuple(name for name, spec in TIME_FRAMES.items() if spec["kind"] == "session")
    assert session == SESSION_TIME_FRAMES

def test_daily_candle_end(calendar):
    # Alpaca stamps a daily candle at midnight New York (05:00 UTC in November)
    assert candle_end(utc(2026, 11, 25, 5), "1Day", calendar) == utc(2026, 11, 25, 21)

def test_weekly_candle_end_uses_early_close(calendar):
    assert candle_end(utc(2026, 11, 23, 5), "1Week", calendar) == utc(2026, 11, 27, 18)

def test_monthly_candle_end(calendar):
    assert candle_end(utc(2026, 11, 1, 4), "1Month", calendar) == utc(2026, 11, 30, 21)

def test_short_calendar_ends_the_week_early():
    # Why the caller must fetch the calendar past the end of the current month
    short = get_calendar(FakeTradingClient(THANKSGIVING_DAYS[:3]), date(2026, 11, 23), date(2026, 11, 25))
    assert candle_end(utc(2026, 11, 23, 5), "1Week", short) == utc(2026, 11, 25, 21)

def test_trading_days_between_skips_holiday(calendar):
    assert trading_days_between(date(2026, 11, 24), date(2026, 11, 27), calendar) == [
        date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 27)]

def test_trading_days_between_includes_both_ends(calendar):
    assert trading_days_between(date(2026, 11, 23), date(2026, 11, 23), calendar) == [date(2026, 11, 23)]

def test_trading_days_between_no_trading_days(calendar):
    assert trading_days_between(date(2026, 11, 28), date(2026, 11, 29), calendar) == []
