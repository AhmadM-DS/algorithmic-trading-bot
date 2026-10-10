"""
watchlist.py
Write to the watchlist table
"""

from pyodbc import IntegrityError
from logger import db_log
from storage.connections import is_duplicate_error

def get_or_create_ticker(conn, ticker, today):
    """Create or retrieve a ticker from tickers table"""
    cursor = conn.cursor()
    cursor.execute("SELECT ticker_id FROM tickers WHERE ticker = ? ",
                   (ticker,)
                   )
    row = cursor.fetchone()
    if row is not None:
        ticker_id = row[0]
        db_log.debug(f"Successfully retrieved {ticker}")
    else:
        cursor.execute(
            "INSERT INTO tickers (ticker, first_seen) "
            "OUTPUT INSERTED.ticker_id "
            "VALUES (?, ?)",
            (ticker, today)
        )
        ticker_id = cursor.fetchone()[0]
        db_log.info(f"{ticker} succesfully created at {today}")
    return ticker_id

def insert_watchlist_hit(conn, ticker, today, source, selected):
    "Insert a ticker into watchlist_history table"
    cursor = conn.cursor()
    ticker_id = get_or_create_ticker(conn, ticker, today)

    try:
        cursor.execute(
            "INSERT INTO watchlist_history ([date], [source], selected, ticker_id) "
            "VALUES (?, ?, ?, ?)",
            (today, source, selected, ticker_id)
        )
        db_log.debug(f"Added {ticker} to watchlist_history")
    except IntegrityError as e:
        if is_duplicate_error(e):
            db_log.info(f"Attempted to add duplicate into watchlist_history for {ticker}. See: {e}")
            return False
        raise
    return True