from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from data.candles import (COLUMNS, split_by_ticker, regular_hours_only, build_candles, regular_hours_volume,
                          request_start, build_request, get_candles)

def alpaca_frame(rows):
    """Build a DataFrame shaped like Alpaca's BarSet.df from (symbol, timestamp, close) tuples"""
    records = [{"symbol": s, "timestamp": pd.Timestamp(t, tz="UTC"), "open": c, "high": c, "low": c,
                "close": c, "volume": 100.0, "trade_count": 1.0, "vwap": c} for s, t, c in rows]
    return pd.DataFrame(records).set_index(["symbol", "timestamp"])

SAMPLE = alpaca_frame([
    ("AAPL", "2026-10-09 19:30", 2.0),
    ("AAPL", "2026-10-09 19:15", 1.0),
    ("NVDA", "2026-10-09 19:15", 5.0),
])

def test_one_frame_per_requested_ticker():
    result = split_by_ticker(SAMPLE, ["AAPL", "NVDA"])
    assert list(result) == ["AAPL", "NVDA"]
    assert len(result["AAPL"]) == 2
    assert len(result["NVDA"]) == 1

def test_columns_are_the_standard():
    for frame in split_by_ticker(SAMPLE, ["AAPL", "NVDA"]).values():
        assert list(frame.columns) == COLUMNS

def test_sorted_oldest_first_with_plain_index():
    aapl = split_by_ticker(SAMPLE, ["AAPL"])["AAPL"]
    assert list(aapl["close"]) == [1.0, 2.0]
    assert list(aapl.index) == [0, 1]

def test_missing_ticker_gets_empty_frame():
    zzzz = split_by_ticker(SAMPLE, ["AAPL", "ZZZZ"])["ZZZZ"]
    assert zzzz.empty
    assert list(zzzz.columns) == COLUMNS

def test_nothing_returned():
    result = split_by_ticker(pd.DataFrame(), ["AAPL", "NVDA"])
    assert all(frame.empty and list(frame.columns) == COLUMNS for frame in result.values())

def test_unrequested_ticker_left_out():
    assert list(split_by_ticker(SAMPLE, ["AAPL"])) == ["AAPL"]

def ny_frame(times):
    """One ticker's frame from UTC timestamp strings"""
    stamps = [pd.Timestamp(t, tz="UTC") for t in times]
    return pd.DataFrame({"timestamp": stamps, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})

# Nov 25 normal day (14:30-21:00 UTC), Nov 27 early close (14:30-18:00 UTC)
CALENDAR = {
    date(2026, 11, 25): {"open": pd.Timestamp("2026-11-25 14:30", tz="UTC"), "close": pd.Timestamp("2026-11-25 21:00", tz="UTC")},
    date(2026, 11, 27): {"open": pd.Timestamp("2026-11-27 14:30", tz="UTC"), "close": pd.Timestamp("2026-11-27 18:00", tz="UTC")},
}

def test_regular_hours_drops_pre_and_after_market():
    frame = ny_frame(["2026-11-25 14:00", "2026-11-25 14:30", "2026-11-25 20:30", "2026-11-25 21:00"])
    kept = regular_hours_only(frame, CALENDAR)
    assert list(kept["timestamp"]) == [pd.Timestamp("2026-11-25 14:30", tz="UTC"), pd.Timestamp("2026-11-25 20:30", tz="UTC")]
    assert list(kept.index) == [0, 1]

def test_regular_hours_early_close():
    frame = ny_frame(["2026-11-27 17:30", "2026-11-27 18:00"])
    assert len(regular_hours_only(frame, CALENDAR)) == 1

def test_regular_hours_drops_non_trading_day():
    frame = ny_frame(["2026-11-26 15:00", "2026-11-28 15:00"])
    assert regular_hours_only(frame, CALENDAR).empty

def test_regular_hours_empty_frame_keeps_columns():
    kept = regular_hours_only(pd.DataFrame(columns=COLUMNS), CALENDAR)
    assert kept.empty
    assert list(kept.columns) == COLUMNS

def thirty_minute_day(day, last="15:30"):
    """Regular-hours 30Min candles for one New York day; open/close count up, high = 100 at 11:00"""
    stamps = pd.date_range(f"{day} 09:30", f"{day} {last}", freq="30min", tz="America/New_York").tz_convert("UTC")
    n = len(stamps)
    return pd.DataFrame({"timestamp": stamps, "open": [float(i) for i in range(n)],
                         "high": [100.0 if i == 3 else float(i) for i in range(n)],
                         "low": [float(i) - 1 for i in range(n)], "close": [float(i) + 0.5 for i in range(n)],
                         "volume": 10.0})

def ny_starts(frame):
    return list(frame["timestamp"].dt.tz_convert("America/New_York").dt.strftime("%m-%d %H:%M"))

def test_four_hour_bins_start_at_open():
    built = build_candles(thirty_minute_day("2026-11-25"), "4Hour")
    assert ny_starts(built) == ["11-25 09:30", "11-25 13:30"]

def test_four_hour_values():
    first = build_candles(thirty_minute_day("2026-11-25"), "4Hour").iloc[0]
    assert first["open"] == 0.0
    assert first["high"] == 100.0
    assert first["low"] == -1.0
    assert first["close"] == 7.5
    assert first["volume"] == 80.0

def test_last_four_hour_candle_is_short():
    assert build_candles(thirty_minute_day("2026-11-25"), "4Hour").iloc[1]["volume"] == 50.0

def test_one_hour_bins():
    built = build_candles(thirty_minute_day("2026-11-25"), "1Hour")
    assert ny_starts(built)[:2] == ["11-25 09:30", "11-25 10:30"]
    assert ny_starts(built)[-1] == "11-25 15:30"

def test_bins_survive_daylight_saving_change():
    frame = pd.concat([thirty_minute_day("2026-10-30"), thirty_minute_day("2026-11-02")], ignore_index=True)
    assert ny_starts(build_candles(frame, "4Hour")) == ["10-30 09:30", "10-30 13:30", "11-02 09:30", "11-02 13:30"]

def test_early_close_day():
    built = build_candles(thirty_minute_day("2026-11-27", last="12:30"), "4Hour")
    assert ny_starts(built) == ["11-27 09:30"]

def test_build_returns_standard_columns_in_utc():
    built = build_candles(thirty_minute_day("2026-11-25"), "1Hour")
    assert list(built.columns) == COLUMNS
    assert str(built["timestamp"].dt.tz) == "UTC"

def test_build_empty_frame():
    built = build_candles(pd.DataFrame(columns=COLUMNS), "4Hour")
    assert built.empty and list(built.columns) == COLUMNS

def daily_frame(days):
    """1Day candles stamped at midnight New York, volume 999 (Alpaca's full-day volume)"""
    stamps = pd.to_datetime(days).tz_localize("America/New_York").tz_convert("UTC")
    return pd.DataFrame({"timestamp": stamps, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 999.0})

def test_daily_volume_is_regular_hours_sum():
    source = thirty_minute_day("2026-11-25")
    result = regular_hours_volume(daily_frame(["2026-11-25"]), source)
    assert result["volume"].iloc[0] == source["volume"].sum()

def test_day_without_source_candles_is_nan():
    result = regular_hours_volume(daily_frame(["2026-11-24", "2026-11-25"]), thirty_minute_day("2026-11-25"))
    assert pd.isna(result["volume"].iloc[0])
    assert result["volume"].iloc[1] == 130.0

def test_no_source_at_all_is_nan():
    result = regular_hours_volume(daily_frame(["2026-11-25"]), pd.DataFrame(columns=COLUMNS))
    assert pd.isna(result["volume"].iloc[0])

def test_empty_daily():
    assert regular_hours_volume(pd.DataFrame(columns=COLUMNS), thirty_minute_day("2026-11-25")).empty

def test_input_frame_unchanged():
    daily = daily_frame(["2026-11-25"])
    regular_hours_volume(daily, thirty_minute_day("2026-11-25"))
    assert daily["volume"].iloc[0] == 999.0

WEEKDAYS_2026 = {date(2026, 1, 1) + pd.Timedelta(days=i): None for i in range(365)
                 if (date(2026, 1, 1) + pd.Timedelta(days=i)).weekday() < 5}
AS_OF = pd.Timestamp("2026-11-25 15:00", tz="UTC")

def test_request_start_intraday():
    # 50 x 15Min = 750 min = 2 days, plus 1 margin day: Mon Nov 23 midnight New York
    assert request_start(AS_OF, "15Min", 50, WEEKDAYS_2026) == pd.Timestamp("2026-11-23 05:00", tz="UTC")

def test_request_start_daily_starts_at_midnight_new_york():
    start = request_start(AS_OF, "1Day", 50, WEEKDAYS_2026)
    assert start.tz_convert("America/New_York").hour == 0

def test_request_start_counts_trading_days_only():
    # 1 x 15Min needs 1 + 1 days; from Monday Nov 23 that's back to Friday Nov 20
    monday = pd.Timestamp("2026-11-23 15:00", tz="UTC")
    assert request_start(monday, "15Min", 1, WEEKDAYS_2026).date() == date(2026, 11, 20)

def test_request_start_calendar_too_short():
    with pytest.raises(ValueError, match="need"):
        request_start(AS_OF, "1Month", 50, WEEKDAYS_2026)

def test_build_request():
    start = pd.Timestamp("2026-11-23 05:00", tz="UTC")
    request = build_request(["AAPL", "NVDA"], "4Hour", start, AS_OF, {"feed": "sip"})
    assert request.symbol_or_symbols == ["AAPL", "NVDA"]
    assert request.timeframe.value == "30Min"
    # alpaca-py stores times as UTC with the timezone label removed
    assert request.start == start.tz_localize(None) and request.end == AS_OF.tz_localize(None)
    assert request.feed.value == "sip"
    assert request.adjustment.value == "split"

class FakeDataClient:
    """Returns Alpaca-shaped bars per time frame and records each request"""
    def __init__(self, bars_by_time_frame):
        self.bars = bars_by_time_frame
        self.requests = []

    def get_stock_bars(self, request):
        self.requests.append(request)
        return SimpleNamespace(df=self.bars.get(request.timeframe.value, pd.DataFrame()))

def alpaca_bars(symbol, ny_times, volume=10.0):
    stamps = pd.to_datetime(ny_times).tz_localize("America/New_York").tz_convert("UTC")
    frame = pd.DataFrame({"symbol": symbol, "timestamp": stamps, "open": 1.0, "high": 1.0, "low": 1.0,
                          "close": [float(i) for i in range(len(stamps))], "volume": volume,
                          "trade_count": 1.0, "vwap": 1.0})
    return frame.set_index(["symbol", "timestamp"])

def ny(text):
    return pd.Timestamp(text, tz="America/New_York").tz_convert("UTC")

NOV_24_25 = {d.date(): {"open": ny(f"{d.date()} 09:30"), "close": ny(f"{d.date()} 16:00")}
             for d in pd.bdate_range("2026-11-02", "2026-11-25")}
LIVE_PROFILE = {"feed": "sip", "lag_minutes": 0, "min_time_frame_minutes": 1}
DELAYED_PROFILE = {"feed": "sip", "lag_minutes": 15, "min_time_frame_minutes": 15}
FIFTEEN = alpaca_bars("AAPL", ["2026-11-25 09:00", "2026-11-25 09:30", "2026-11-25 09:45", "2026-11-25 10:00", "2026-11-25 10:15"])

def test_get_candles_drops_pre_market_and_forming_candle():
    client = FakeDataClient({"15Min": FIFTEEN})
    out = get_candles(client, ["AAPL"], "15Min", 10, LIVE_PROFILE, ny("2026-11-25 10:20"), NOV_24_25)
    assert ny_starts(out["AAPL"]) == ["11-25 09:30", "11-25 09:45", "11-25 10:00"]
    assert len(client.requests) == 1

def test_get_candles_keeps_last_lookback():
    out = get_candles(FakeDataClient({"15Min": FIFTEEN}), ["AAPL"], "15Min", 2, LIVE_PROFILE, ny("2026-11-25 10:20"), NOV_24_25)
    assert ny_starts(out["AAPL"]) == ["11-25 09:45", "11-25 10:00"]

def test_get_candles_delayed_plan_sees_less():
    out = get_candles(FakeDataClient({"15Min": FIFTEEN}), ["AAPL"], "15Min", 10, DELAYED_PROFILE, ny("2026-11-25 10:20"), NOV_24_25)
    # data clock 10:05: the 10:00 candle ends 10:15, not closed yet
    assert ny_starts(out["AAPL"])[-1] == "11-25 09:45"

def test_get_candles_request_uses_data_clock_and_feed():
    client = FakeDataClient({"15Min": FIFTEEN})
    get_candles(client, ["AAPL"], "15Min", 10, DELAYED_PROFILE, ny("2026-11-25 10:20"), NOV_24_25)
    assert client.requests[0].end == ny("2026-11-25 10:05").tz_localize(None)
    assert client.requests[0].feed.value == "sip"

def test_get_candles_built_time_frame_requests_30min():
    thirty = alpaca_bars("AAPL", pd.date_range("2026-11-25 09:30", "2026-11-25 15:30", freq="30min"))
    client = FakeDataClient({"30Min": thirty})
    out = get_candles(client, ["AAPL"], "4Hour", 10, LIVE_PROFILE, ny("2026-11-25 16:05"), NOV_24_25)
    assert client.requests[0].timeframe.value == "30Min"
    assert ny_starts(out["AAPL"]) == ["11-25 09:30", "11-25 13:30"]

def test_get_candles_daily_volume_and_open_day():
    daily = alpaca_bars("AAPL", ["2026-11-24 00:00", "2026-11-25 00:00"], volume=999.0)
    thirty = alpaca_bars("AAPL", ["2026-11-24 08:00", "2026-11-24 09:30", "2026-11-24 15:30", "2026-11-25 09:30"], volume=10.0)
    client = FakeDataClient({"1Day": daily, "30Min": thirty})
    out = get_candles(client, ["AAPL"], "1Day", 10, LIVE_PROFILE, ny("2026-11-25 12:00"), NOV_24_25)
    assert len(client.requests) == 2
    assert ny_starts(out["AAPL"]) == ["11-24 00:00"]
    assert out["AAPL"]["volume"].iloc[0] == 20.0

def test_get_candles_missing_ticker():
    out = get_candles(FakeDataClient({"15Min": FIFTEEN}), ["AAPL", "ZZZZ"], "15Min", 10, LIVE_PROFILE, ny("2026-11-25 10:20"), NOV_24_25)
    assert out["ZZZZ"].empty and list(out["ZZZZ"].columns) == COLUMNS

def test_get_candles_nothing_returned():
    out = get_candles(FakeDataClient({}), ["AAPL"], "1Day", 10, LIVE_PROFILE, ny("2026-11-25 12:00"), NOV_24_25)
    assert out["AAPL"].empty and list(out["AAPL"].columns) == COLUMNS

def test_get_candles_logs_summary(caplog):
    caplog.set_level("DEBUG", logger="api")
    get_candles(FakeDataClient({"15Min": FIFTEEN}), ["AAPL", "ZZZZ"], "15Min", 10, LIVE_PROFILE, ny("2026-11-25 10:20"), NOV_24_25)
    assert "15Min 2 tickers, 3 candles, empty: ['ZZZZ']" in caplog.text
