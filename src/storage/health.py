"""
health.py
Write to the data_health table and read the database's own size
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

def database_size(conn) -> tuple:
    """Return the space the database's data files use and the most it may grow to, in MB

    Only data files count (not the log), as Azure's size limit does. The max comes from the server, never a fixed
    number, so a tier change moves it by itself.

    Parameters:
        conn (Connection): An open database connection

    Returns:
        (used_mb, max_mb); max_mb is None when the server reports no limit (SQL Express gives NULL, unlimited is -1)
    """
    row = conn.cursor().execute(
        "SELECT CAST(SUM(CAST(FILEPROPERTY(name, 'SpaceUsed') AS BIGINT)) * 8 / 1024 AS INT) AS used_mb, "
        "CAST(DATABASEPROPERTYEX(DB_NAME(), 'MaxSizeInBytes') AS BIGINT) AS max_bytes "
        "FROM sys.database_files WHERE type = 0"
    ).fetchone()
    max_mb = row.max_bytes // (1024 * 1024) if row.max_bytes and row.max_bytes > 0 else None
    return row.used_mb, max_mb
