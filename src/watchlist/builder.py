"""
builder.py
Build the daily watchlist: screener hits first, then popular tickers up to the cap
"""

#Local Imports
from logger import routine_log
from storage.events import insert_bot_event
from storage.watchlist import (get_inactive_tickers, get_popular_tickers, get_ticker_states, insert_watchlist_hit,
                               set_ticker_active)
from watchlist.tradable import TICKER_NOT_TRADABLE

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

def _switch_off_untradable(conn, tickers: list):
    """Set is_active = 0 at once for screener hits Alpaca can't trade that are still marked tradable

    A hit seen for the first time is saved with the default is_active = 1, so without this its flag would be
    wrong until the next day's sync.
    """
    states = get_ticker_states(conn)
    for ticker in tickers:
        if states.get(ticker):
            set_ticker_active(conn, ticker, False)
            insert_bot_event(conn, TICKER_NOT_TRADABLE, f"{ticker}: screener hit not in Alpaca's tradable list")

def build_watchlist(conn, screened: list, today, source: str, min_trades: int, max_tickers: int,
                    tradable: set | None = None) -> list:
    """Make today's watchlist and save every screener hit

    Only screener hits are saved to watchlist_history, never popular fills: popularity is
    ranked by days in watchlist_history, so saving fills would make a ticker rank itself higher.
    Run tradable.sync_tradable first so saved tickers' is_active is current; tradable also keeps out a
    screener hit seen for the first time that Alpaca can't trade, gives its slot to the next popular ticker,
    and sets its is_active = 0 right away (with a bot_events row). Doesn't commit; the caller commits and
    sends the Discord message.

    Parameters:
        conn (Connection): An open database connection
        screened (list): Today's screener hits
        today (date): The New York trading date
        source (str): Which screener found the hits, e.g. "biggest-gainers"
        min_trades (int): MIN_TRADES_FOR_POPULAR from constants.py
        max_tickers (int): MAX_TICKERS from constants.py
        tradable (set | None): Alpaca's tradable symbols; None skips that filter

    Returns:
        Today's watchlist, screener hits first
    """
    inactive = get_inactive_tickers(conn)
    if tradable is not None:
        inactive |= {ticker for ticker in screened if ticker not in tradable}
    popular = get_popular_tickers(conn, max_tickers, min_trades)
    final = combine(screened, popular, inactive, max_tickers)
    saved = sum(insert_watchlist_hit(conn, t, today, source, t in final) for t in screened)
    if tradable is not None:
        _switch_off_untradable(conn, [ticker for ticker in screened if ticker not in tradable])
    routine_log.info(f"Watchlist {today}: {len(final)} tickers ({len(screened)} screened, "
                     f"{saved} hits saved, {len(screened) - saved} duplicates): {final}")
    return final
