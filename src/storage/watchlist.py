"""
watchlist.py
Read and write the tickers and watchlist_history tables
"""

#Third Party Libraries
from pyodbc import IntegrityError

#Local Imports
from logger import db_log
from storage.connections import is_duplicate_error

def get_or_create_ticker(conn, ticker, today):
    """Return a ticker's id, creating the ticker if it doesn't exist yet

    first_seen is only set when the ticker is created. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        ticker (str): The ticker symbol
        today (date): The New York trading date, saved as first_seen for a new ticker

    Returns:
        The ticker_id as an int
    """
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
    """Save one screener hit to watchlist_history

    Creates the ticker first if needed. A repeat of the same (date, ticker, source)
    is logged and skipped. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        ticker (str): The ticker symbol
        today (date): The New York trading date of the hit
        source (str): Which screener found it, e.g. "biggest-gainers"
        selected (bool): True if the ticker made the final watchlist

    Returns:
        True if saved, False if it was a duplicate

    Raises:
        pyodbc.IntegrityError for any database error other than a duplicate
    """
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

def get_popular_tickers(conn, limit, min_trades):
    """Return the best tickers to fill empty watchlist slots

    Ranked by days appeared in the screener, then by profitable trades (only counted once a
    ticker has min_trades closed trades). Left out: is_active = 0, fill_override = 0, and a net
    loss after min_trades closed trades unless fill_override = 1.

    Parameters:
        conn (Connection): An open database connection
        limit (int): The most tickers to return
        min_trades (int): MIN_TRADES_FOR_POPULAR from constants.py

    Returns:
        A list of ticker symbols, best first
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT TOP (?) ticker FROM v_ticker_stats "
        "WHERE is_active = 1 AND days_appeared > 0 "
        "AND ISNULL(fill_override, CASE WHEN closed_positions >= ? AND total_realized_pnl < 0 THEN 0 ELSE 1 END) = 1 "
        "ORDER BY days_appeared DESC, "
        "CASE WHEN closed_positions >= ? THEN profitable_trades ELSE 0 END DESC, ticker",
        (limit, min_trades, min_trades),
    )
    return [row[0] for row in cursor.fetchall()]

def get_inactive_tickers(conn):
    """Return the tickers that can't be traded (is_active = 0)

    Parameters:
        conn (Connection): An open database connection

    Returns:
        A set of ticker symbols
    """
    cursor = conn.cursor()
    cursor.execute("SELECT ticker FROM tickers WHERE is_active = 0")
    return {row[0] for row in cursor.fetchall()}
