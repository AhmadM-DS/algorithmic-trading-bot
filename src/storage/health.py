"""
health.py
Write to the data_health table
"""

#Third Party Libraries
import pandas as pd

#Local Imports
from logger import db_log
from storage.connections import to_db_time
from storage.watchlist import get_or_create_ticker
from data.market_calendar import NEW_YORK

def insert_data_health(conn, ticker, row):
    """Insert one data_health row from quality.check_candles

    Gets or creates the ticker first (first_seen = the New York date of checked_at).
    No duplicate handling: the table has no UNIQUE constraint. The caller commits.

    Parameters:
        conn (Connection): An open database connection
        ticker (str): The ticker symbol
        row (dict): A row from check_candles; keys match the data_health columns
    """
    ticker_id = get_or_create_ticker(conn, ticker, pd.Timestamp(row["checked_at"]).tz_convert(NEW_YORK).date())
    conn.cursor().execute(
        "INSERT INTO data_health (checked_at, time_frame, missing_candles, stale_last_timestamp, zero_volume, "
        "duplicates, empty_values, lag_seconds, market_data_plan, [status], ticker_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (to_db_time(row["checked_at"]), row["time_frame"], row["missing_candles"],
         to_db_time(row["stale_last_timestamp"]), row["zero_volume"], row["duplicates"], row["empty_values"],
         row["lag_seconds"], row["market_data_plan"], row["status"], ticker_id),
    )
    db_log.debug(f"data_health saved: {ticker} {row['time_frame']} {row['status']}")
