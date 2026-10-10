from datetime import date, datetime, timezone

import pytest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config.constants import MARKET_DATA_PROFILES
from data.time_frames import (TIME_FRAMES, to_minutes, kind, fetch_as, to_alpaca,
                              is_allowed, data_now, candle_end, is_closed)

def utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

# EST (UTC-5) after Nov 1: 9:30 NY = 14:30 UTC, 13:00 NY = 18:00 UTC, 16:00 NY = 21:00 UTC
CALENDAR = {
    date(2026, 11, 25): {"open": utc(2026, 11, 25, 14, 30), "close": utc(2026, 11, 25, 21)},
    date(2026, 11, 27): {"open": utc(2026, 11, 27, 14, 30), "close": utc(2026, 11, 27, 18)},
}

DELAYED = MARKET_DATA_PROFILES["delayed"]
LIVE = MARKET_DATA_PROFILES["live"]

def test_every_time_frame_has_kind_and_minutes():
    for spec in TIME_FRAMES.values():
        assert spec["kind"] in ("intraday", "built", "session")
        assert spec["minutes"] > 0

def test_built_sources_are_fetchable():
    for time_frame, spec in TIME_FRAMES.items():
        if spec["kind"] == "built":
            assert kind(spec["source"]) != "built", time_frame

def test_every_time_frame_converts_to_alpaca():
    for time_frame in TIME_FRAMES:
        assert isinstance(to_alpaca(time_frame), TimeFrame)

def test_unknown_time_frame_raises():
    for function in (to_minutes, kind, fetch_as, to_alpaca):
        with pytest.raises(ValueError, match="2Hour"):
            function("2Hour")

def test_fetch_as():
    assert fetch_as("15Min") == "15Min"
    assert fetch_as("4Hour") == "30Min"
    assert fetch_as("1Day") == "1Day"

def test_to_alpaca():
    assert to_alpaca("15Min").value == TimeFrame(15, TimeFrameUnit.Minute).value
    assert to_alpaca("1Hour").value == TimeFrame(30, TimeFrameUnit.Minute).value
    assert to_alpaca("1Week").value == TimeFrame(1, TimeFrameUnit.Week).value

def test_is_allowed_by_plan():
    assert not is_allowed("5Min", DELAYED)
    assert is_allowed("15Min", DELAYED)
    assert is_allowed("1Day", DELAYED)
    assert is_allowed("1Min", LIVE)

def test_data_now_subtracts_lag():
    now = utc(2026, 11, 25, 15)
    assert data_now(now, DELAYED) == utc(2026, 11, 25, 14, 45)
    assert data_now(now, LIVE) == now

def test_intraday_candle_end():
    assert candle_end(utc(2026, 11, 25, 15), "15Min", CALENDAR) == utc(2026, 11, 25, 15, 15)

def test_built_candle_end_normal():
    # 9:30-13:30 NY
    assert candle_end(utc(2026, 11, 25, 14, 30), "4Hour", CALENDAR) == utc(2026, 11, 25, 18, 30)

def test_built_candle_end_stops_at_close():
    # 13:30 NY candle ends at the 16:00 close, not 17:30
    assert candle_end(utc(2026, 11, 25, 18, 30), "4Hour", CALENDAR) == utc(2026, 11, 25, 21)

def test_built_candle_end_early_close():
    # 9:30 NY candle on the day after Thanksgiving ends at the 13:00 close
    assert candle_end(utc(2026, 11, 27, 14, 30), "4Hour", CALENDAR) == utc(2026, 11, 27, 18)

def test_is_closed_at_exact_end():
    start = utc(2026, 11, 25, 15)
    assert not is_closed(start, "15Min", utc(2026, 11, 25, 15, 14), CALENDAR)
    assert is_closed(start, "15Min", utc(2026, 11, 25, 15, 15), CALENDAR)
