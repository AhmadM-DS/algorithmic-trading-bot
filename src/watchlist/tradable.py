"""
tradable.py
Keep tickers.is_active matching what Alpaca can trade: once a day from the asset list, and at once on a rejection
"""

#Local Imports
from logger import trades_log
from notifications import send_trades
from storage.events import insert_bot_event
from storage.watchlist import get_ticker_states, set_ticker_active

TICKER_NOT_TRADABLE = "ticker_not_tradable"
TICKER_TRADABLE = "ticker_tradable"
NOT_TRADABLE_PHRASES = ("not tradable", "not active")

def sync_tradable(conn, tradable: set, alert=send_trades) -> dict:
    """Set is_active for every saved ticker from Alpaca's list, both ways, and note each change once

    The bot owns is_active (= Alpaca can trade it); the admin's fill_override is never touched. An empty list
    can only be a bad answer, so it changes nothing. Commits.

    Parameters:
        conn (Connection): An open database connection
        tradable (set): Every symbol Alpaca can trade, from AlpacaBroker.get_tradable_tickers
        alert (callable): Sends the trades-channel note; Discord by default

    Returns:
        {"off": tickers switched off, "on": tickers switched back on}, each sorted
    """
    if not tradable:
        trades_log.warning("Alpaca's tradable list came back empty; is_active left as it was")
        return {"off": [], "on": []}
    states = get_ticker_states(conn)
    off = sorted(ticker for ticker, active in states.items() if active and ticker not in tradable)
    on = sorted(ticker for ticker, active in states.items() if not active and ticker in tradable)
    for ticker in off:
        set_ticker_active(conn, ticker, False)
        insert_bot_event(conn, TICKER_NOT_TRADABLE, f"{ticker}: not in Alpaca's tradable list")
    for ticker in on:
        set_ticker_active(conn, ticker, True)
        insert_bot_event(conn, TICKER_TRADABLE, f"{ticker}: back in Alpaca's tradable list")
    conn.commit()
    if off or on:
        message = (f"Tradable tickers updated from Alpaca. Off: {', '.join(off) or 'none'}. "
                   f"Back on: {', '.join(on) or 'none'}.")
        trades_log.info(message)
        alert(message)
    return {"off": off, "on": on}

def is_not_tradable_rejection(reason: str) -> bool:
    """Return True if Alpaca refused an order because it can't trade the asset

    The message must name the asset, so an account-level refusal (e.g. "account is not active") never
    switches a ticker off.
    """
    reason = reason.lower()
    return "asset" in reason and any(phrase in reason for phrase in NOT_TRADABLE_PHRASES)

def mark_not_tradable(conn, ticker: str, reason: str):
    """Switch a ticker off right after Alpaca refused it as not tradable, so no strategy tries it again today

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        ticker (str): The ticker symbol
        reason (str): Alpaca's rejection message
    """
    set_ticker_active(conn, ticker, False)
    insert_bot_event(conn, TICKER_NOT_TRADABLE, f"{ticker}: order rejected ({reason})")
    trades_log.warning(f"{ticker} marked not tradable after a rejection: {reason}")
