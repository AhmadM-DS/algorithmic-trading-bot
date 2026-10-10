from datetime import date

import pandas as pd
import pytest

from storage.health import insert_data_health

def ny(text):
    return pd.Timestamp(text, tz="America/New_York")

def health_row(**changes):
    row = {"checked_at": ny("2026-11-24 10:30"), "time_frame": "15Min", "missing_candles": 1,
           "stale_last_timestamp": None, "zero_volume": 0, "duplicates": 0, "empty_values": 0,
           "lag_seconds": 900, "market_data_plan": "delayed", "status": "ok"}
    row.update(changes)
    return row

def saved(conn):
    return conn.execute("SELECT dh.*, t.ticker, t.first_seen FROM data_health dh "
                        "JOIN tickers t ON t.ticker_id = dh.ticker_id").fetchall()

def test_row_is_saved_with_ticker(bot_conn):
    insert_data_health(bot_conn, "AAPL", health_row())
    rows = saved(bot_conn)
    assert len(rows) == 1
    assert rows[0].ticker == "AAPL" and rows[0].first_seen == date(2026, 11, 24)
    assert rows[0].missing_candles == 1 and rows[0].lag_seconds == 900
    assert rows[0].market_data_plan == "delayed" and rows[0].status == "ok"

def test_times_are_stored_in_utc(bot_conn):
    insert_data_health(bot_conn, "AAPL", health_row(stale_last_timestamp=ny("2026-11-24 10:00"), status="bad"))
    row = saved(bot_conn)[0]
    assert row.checked_at == pd.Timestamp("2026-11-24 15:30").to_pydatetime()
    assert row.stale_last_timestamp == pd.Timestamp("2026-11-24 15:00").to_pydatetime()

def test_empty_ticker_row_with_nulls(bot_conn):
    insert_data_health(bot_conn, "ZZZZ", health_row(missing_candles=0, lag_seconds=None, status="bad"))
    row = saved(bot_conn)[0]
    assert row.lag_seconds is None and row.stale_last_timestamp is None

def test_existing_ticker_reused(bot_conn):
    insert_data_health(bot_conn, "AAPL", health_row())
    insert_data_health(bot_conn, "AAPL", health_row(time_frame="1Day"))
    assert bot_conn.execute("SELECT COUNT(*) FROM tickers").fetchone()[0] == 1

def test_invalid_status_rejected(bot_conn):
    with pytest.raises(Exception, match="ck_data_health_status"):
        insert_data_health(bot_conn, "AAPL", health_row(status="fine"))
