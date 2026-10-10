"""
builder.py
Build the daily watchlist: screener hits first, then popular tickers up to the cap
"""

#Local Imports
from logger import routine_log
from storage.watchlist import get_popular_tickers, get_inactive_tickers, insert_watchlist_hit

def combine(screened: list, popular: list, inactive: set, max_tickers: int) -> list:
    """Return the final watchlist from screener hits and popular tickers

    Screener hits come first so they always get a slot. No repeats, nothing inactive.

    Parameters:
        screened (list): Today's screener hits
        popular (list): Tickers from get_popular_tickers, best first
        inactive (set): Tickers from get_inactive_tickers
        max_tickers (int): MAX_TICKERS from constants.py

    Returns:
        A list of at most max_tickers ticker symbols
    """
    final = []
    for ticker in screened + popular:
        if ticker not in final and ticker not in inactive:
            final.append(ticker)
    return final[:max_tickers]

def build_watchlist(conn, screened: list, today, source: str, min_trades: int, max_tickers: int) -> list:
    """Make today's watchlist and save every screener hit

    Only screener hits are saved to watchlist_history, never popular fills: popularity is
    ranked by days in watchlist_history, so saving fills would make a ticker rank itself higher.
    Doesn't commit; the caller commits and sends the Discord message.

    Parameters:
        conn (Connection): An open database connection
        screened (list): Today's screener hits
        today (date): The New York trading date
        source (str): Which screener found the hits, e.g. "biggest-gainers"
        min_trades (int): MIN_TRADES_FOR_POPULAR from constants.py
        max_tickers (int): MAX_TICKERS from constants.py

    Returns:
        Today's watchlist, screener hits first
    """
    inactive = get_inactive_tickers(conn)
    popular = get_popular_tickers(conn, max_tickers, min_trades)
    final = combine(screened, popular, inactive, max_tickers)
    saved = sum(insert_watchlist_hit(conn, t, today, source, t in final) for t in screened)
    routine_log.info(f"Watchlist {today}: {len(final)} tickers ({len(screened)} screened, "
                     f"{saved} hits saved, {len(screened) - saved} duplicates): {final}")
    return final
