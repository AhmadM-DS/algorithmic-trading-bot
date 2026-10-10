from datetime import date

import pandas as pd
import pytest

from config.constants import DATA_HEALTH_THRESHOLDS
from data.candles import COLUMNS
from data.quality import (period_key, expected_starts, count_missing, count_duplicates, count_zero_volume,
                          count_empty, stale_timestamp, lag_seconds, grade, check_candles, should_save)

NY = "America/New_York"

def ny(text):
    return pd.Timestamp(text, tz=NY).tz_convert("UTC")

# Weekdays Oct 26 - Nov 25, 2026; Nov 25 pretends to close early at 13:00
CALENDAR = {d.date(): {"open": ny(f"{d.date()} 09:30"), "close": ny(f"{d.date()} 16:00")}
            for d in pd.bdate_range("2026-10-26", "2026-11-25")}
CALENDAR[date(2026, 11, 25)]["close"] = ny("2026-11-25 13:00")

def frame(times, volume=10.0):
    return pd.DataFrame({"timestamp": [ny(t) for t in times], "open": 1.0, "high": 1.0, "low": 1.0,
                         "close": 1.0, "volume": volume})

EMPTY = pd.DataFrame(columns=COLUMNS)
OVERNIGHT_GAP = frame(["2026-11-23 15:30", "2026-11-23 15:45", "2026-11-24 09:30", "2026-11-24 10:00"])

def test_period_key_session_kinds():
    ts = ny("2026-11-23 00:00")
    assert period_key(ts, "1Day") == date(2026, 11, 23)
    assert period_key(ts, "1Week") == (2026, 48)
    assert period_key(ts, "1Month") == (2026, 11)
    assert period_key(ts, "15Min") == ts

def test_expected_starts_early_close_4hour():
    assert expected_starts("4Hour", date(2026, 11, 25), date(2026, 11, 25), CALENDAR) == [ny("2026-11-25 09:30")]

def test_expected_starts_skips_weekend():
    starts = expected_starts("1Day", date(2026, 11, 20), date(2026, 11, 23), CALENDAR)
    assert [ts.tz_convert(NY).date() for ts in starts] == [date(2026, 11, 20), date(2026, 11, 23)]

def test_missing_ignores_overnight():
    # the only gap is 09:45 on Nov 24; 16:00 to 09:30 overnight isn't missing
    assert count_missing(OVERNIGHT_GAP, "15Min", CALENDAR) == 1

def test_missing_built_kind():
    assert count_missing(frame(["2026-11-23 09:30", "2026-11-23 13:30", "2026-11-24 13:30"]), "4Hour", CALENDAR) == 1

def test_missing_daily_across_weekend():
    assert count_missing(frame(["2026-11-20 00:00", "2026-11-24 00:00"]), "1Day", CALENDAR) == 1

def test_missing_weekly():
    assert count_missing(frame(["2026-11-02 00:00", "2026-11-16 00:00"]), "1Week", CALENDAR) == 1

def test_missing_none_and_empty():
    assert count_missing(frame(["2026-11-24 09:30", "2026-11-24 09:45"]), "15Min", CALENDAR) == 0
    assert count_missing(EMPTY, "15Min", CALENDAR) == 0

def test_simple_counts():
    assert count_duplicates(frame(["2026-11-24 10:00", "2026-11-24 10:00"])) == 1
    assert count_zero_volume(frame(["2026-11-24 10:00"], volume=0.0)) == 1
    assert count_empty(frame(["2026-11-24 10:00"], volume=float("nan"))) == 1
    assert count_duplicates(EMPTY) == count_zero_volume(EMPTY) == count_empty(EMPTY) == 0

def test_stale_over_threshold():
    # last candle 10:00; at 10:50 the 10:15 and 10:30 candles have closed: 2 behind
    assert stale_timestamp(OVERNIGHT_GAP, "15Min", ny("2026-11-24 10:50"), 1, CALENDAR) == ny("2026-11-24 10:00")

def test_not_stale_within_threshold():
    assert stale_timestamp(OVERNIGHT_GAP, "15Min", ny("2026-11-24 10:50"), 2, CALENDAR) is None

def test_friday_close_not_stale_monday_morning():
    assert stale_timestamp(frame(["2026-11-20 15:45"]), "15Min", ny("2026-11-23 09:40"), 1, CALENDAR) is None

def test_lag_seconds():
    # 10:00 candle ends 10:15; now 10:30
    assert lag_seconds(OVERNIGHT_GAP, "15Min", ny("2026-11-24 10:30"), CALENDAR) == 900
    assert lag_seconds(EMPTY, "15Min", ny("2026-11-24 10:30"), CALENDAR) is None

def healthy_row(**changes):
    row = {"missing_candles": 0, "zero_volume": 0, "duplicates": 0, "empty_values": 0, "stale_last_timestamp": None}
    row.update(changes)
    return row

@pytest.mark.parametrize("changes, has_candles, expected", [
    ({}, True, "ok"),
    ({}, False, "bad"),
    ({"duplicates": 1}, True, "bad"),
    ({"empty_values": 1}, True, "bad"),
    ({"stale_last_timestamp": ny("2026-11-24 10:00")}, True, "bad"),
    ({"missing_candles": 3}, True, "warn"),
    ({"missing_candles": 2}, True, "ok"),
    ({"zero_volume": 1}, True, "warn"),
])
def test_grade(changes, has_candles, expected):
    assert grade(healthy_row(**changes), DATA_HEALTH_THRESHOLDS, has_candles) == expected

def test_check_candles_row_matches_table_columns():
    row = check_candles(OVERNIGHT_GAP, "15Min", ny("2026-11-24 10:30"), ny("2026-11-24 10:15"), "delayed",
                        DATA_HEALTH_THRESHOLDS, CALENDAR)
    assert set(row) == {"checked_at", "time_frame", "missing_candles", "stale_last_timestamp", "zero_volume",
                        "duplicates", "empty_values", "lag_seconds", "market_data_plan", "status"}
    assert row["missing_candles"] == 1 and row["status"] == "ok"
    assert row["market_data_plan"] == "delayed"

def test_check_candles_empty_is_bad():
    row = check_candles(EMPTY, "15Min", ny("2026-11-24 10:30"), ny("2026-11-24 10:15"), "delayed",
                        DATA_HEALTH_THRESHOLDS, CALENDAR)
    assert row["status"] == "bad" and row["lag_seconds"] is None

@pytest.mark.parametrize("status, mode, expected", [
    ("ok", "failures", False), ("warn", "failures", True), ("bad", "failures", True), ("ok", "all", True),
])
def test_should_save(status, mode, expected):
    assert should_save(status, mode) == expected

def test_should_save_unknown_mode():
    with pytest.raises(ValueError, match="failure"):
        should_save("ok", "failure")
