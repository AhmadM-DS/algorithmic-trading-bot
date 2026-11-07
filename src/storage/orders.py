"""
orders.py
Read and write the orders table
"""

#Standard Library
from datetime import datetime
from decimal import Decimal

#Local Imports
from logger import db_log
from storage.fills import FINAL_STATUSES

REJECT_REASON_LENGTH = 256
STUCK_STATUSES = ("submitting", "unknown")
DONE_STATUSES = FINAL_STATUSES + ("not_sent",)

def _check_one_row(cursor, order_id: int):
    """Raise if an update didn't change exactly one order"""
    if cursor.rowcount != 1:
        raise LookupError(f"Expected to update 1 order with order_id {order_id}, updated {cursor.rowcount}")

def insert_order(conn, *, client_order_id: str, side: str, quantity: int, order_type: str, time_in_force: str,
                 submitted_at: datetime, status: str, strategy_id: int, ticker_id: int,
                 request_price: Decimal | None = None, signal_id: int | None = None,
                 position_id: int | None = None, parent_order_id: int | None = None,
                 alpaca_order_id: str | None = None, exit_reason: str | None = None) -> int:
    """Save one order and return its order_id

    A buy is saved with status "submitting" before it's sent to Alpaca; bracket legs are saved
    after Alpaca answers, with their Alpaca IDs and parent_order_id. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        client_order_id (str): The bot's own ID for the order (Alpaca's for a bracket leg)
        side (str): "buy" or "sell"
        quantity (int): The number of shares asked for, above 0
        order_type (str): Alpaca's order type, e.g. "market", "stop", "limit"
        time_in_force (str): Alpaca's time in force, e.g. "day", "gtc"
        submitted_at (datetime): When the bot saved the order, in UTC
        status (str): "submitting" for a new order, Alpaca's status for a leg
        strategy_id (int): The strategy that placed it
        ticker_id (int): The ticker's id
        request_price (Decimal | None): The price risk sized with, or a leg's stop / limit price
        signal_id (int | None): The signal that produced it, if any
        position_id (int | None): The position an exit order closes, if known
        parent_order_id (int | None): The buy a bracket leg belongs to
        alpaca_order_id (str | None): Alpaca's ID, if already known
        exit_reason (str | None): Why a sell was placed, e.g. "end_of_day" or "stop_loss"; None on buys

    Returns:
        The new order_id as an int

    Raises:
        pyodbc.IntegrityError if the client_order_id is already saved or a CHECK / foreign key fails
    """
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (client_order_id, alpaca_order_id, side, requested_quantity, order_type, time_in_force, submitted_at, [status], "
        "request_price, strategy_id, ticker_id, signal_id, position_id, parent_order_id, exit_reason) "
        "OUTPUT INSERTED.order_id "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (client_order_id, alpaca_order_id, side, quantity, order_type, time_in_force, submitted_at, status,
         request_price, strategy_id, ticker_id, signal_id, position_id, parent_order_id, exit_reason),
    )
    order_id = cursor.fetchone()[0]
    db_log.debug(f"orders saved: {client_order_id} as order_id {order_id} ({status})")
    return order_id

def save_broker_answer(conn, order_id: int, alpaca_order_id: str, status: str, filled_quantity: int,
                       filled_price: Decimal | None):
    """Copy Alpaca's version of an order onto its row

    Called when Alpaca accepts the order or when a lookup by client_order_id finds it.
    Leaves the request columns as they were. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        order_id (int): The order's row
        alpaca_order_id (str): Alpaca's ID for the order
        status (str): Alpaca's status, e.g. "accepted", "filled"
        filled_quantity (int): Shares filled so far, as Alpaca reports
        filled_price (Decimal | None): Alpaca's average fill price, None if nothing filled

    Raises:
        LookupError if no order has that order_id
    """
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE orders SET alpaca_order_id = ?, [status] = ?, filled_quantity = ?, filled_price = ? WHERE order_id = ?",
        (alpaca_order_id, status, filled_quantity, filled_price, order_id),
    )
    _check_one_row(cursor, order_id)
    db_log.debug(f"orders updated: order_id {order_id} is {status} at Alpaca ({alpaca_order_id})")

def save_rejection(conn, order_id: int, reject_reason: str):
    """Mark an order as rejected and keep Alpaca's reason

    The reason is cut to the column's 256 characters. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        order_id (int): The order's row
        reject_reason (str): Alpaca's error message

    Raises:
        LookupError if no order has that order_id
    """
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE orders SET [status] = 'rejected', reject_reason = ? WHERE order_id = ?",
        (reject_reason[:REJECT_REASON_LENGTH], order_id),
    )
    _check_one_row(cursor, order_id)
    db_log.debug(f"orders updated: order_id {order_id} rejected")

def set_order_status(conn, order_id: int, status: str):
    """Change only an order's status

    For the bot's own statuses: "unknown" (every retry failed) and "not_sent" (Alpaca never got it).
    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        order_id (int): The order's row
        status (str): The new status

    Raises:
        LookupError if no order has that order_id
    """
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE orders SET [status] = ? WHERE order_id = ?",
        (status, order_id),
    )
    _check_one_row(cursor, order_id)
    db_log.debug(f"orders updated: order_id {order_id} is {status}")

def get_stuck_orders(conn, before: datetime) -> list:
    """Return orders still "submitting" or "unknown" that were saved before a time

    Each cycle looks these up at Alpaca by client_order_id to settle them.

    Parameters:
        conn (Connection): An open database connection
        before (datetime): Only orders saved before this UTC time, e.g. now minus one minute

    Returns:
        A list of {"order_id", "client_order_id", "status", "strategy_id", "ticker_id", "signal_id"},
        oldest first
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT order_id, client_order_id, [status], strategy_id, ticker_id, signal_id FROM orders WHERE [status] IN (?, ?) AND submitted_at < ? ORDER BY submitted_at",
        (*STUCK_STATUSES, before),
    )
    return [{"order_id": row.order_id, "client_order_id": row.client_order_id, "status": row.status,
             "strategy_id": row.strategy_id, "ticker_id": row.ticker_id, "signal_id": row.signal_id}
            for row in cursor.fetchall()]

def get_open_orders(conn) -> list:
    """Return every order that isn't done yet, leaving out bracket legs

    "Not done" = any status but DONE_STATUSES, so "submitting" and "unknown" count (they may be at Alpaca).
    Legs are left out: they wait for as long as their position is open, and E3 cancels them before a sell.

    Parameters:
        conn (Connection): An open database connection

    Returns:
        A list of {"strategy_id", "ticker", "side"}, one per order
    """
    placeholders = ", ".join("?" * len(DONE_STATUSES))
    rows = conn.cursor().execute(
        "SELECT o.strategy_id, t.ticker, o.side FROM orders o JOIN tickers t ON t.ticker_id = o.ticker_id "
        f"WHERE o.parent_order_id IS NULL AND o.[status] NOT IN ({placeholders})",
        DONE_STATUSES,
    ).fetchall()
    return [{"strategy_id": row.strategy_id, "ticker": row.ticker, "side": row.side} for row in rows]

def get_pending_buys(conn) -> list:
    """Return the buy orders not done yet with shares still to fill, for risk's exposure

    Parameters:
        conn (Connection): An open database connection

    Returns:
        A list of {"strategy_id", "ticker", "unfilled", "request_price", "position_id"}; request_price is
        None for an order the bot didn't size (a manual trade)
    """
    placeholders = ", ".join("?" * len(DONE_STATUSES))
    rows = conn.cursor().execute(
        "SELECT o.strategy_id, t.ticker, o.requested_quantity - o.filled_quantity AS unfilled, o.request_price, "
        "o.position_id FROM orders o JOIN tickers t ON t.ticker_id = o.ticker_id "
        f"WHERE o.side = 'buy' AND o.filled_quantity < o.requested_quantity AND o.[status] NOT IN ({placeholders}) "
        "ORDER BY o.order_id",
        DONE_STATUSES,
    ).fetchall()
    return [{"strategy_id": row.strategy_id, "ticker": row.ticker, "unfilled": row.unfilled,
             "request_price": row.request_price, "position_id": row.position_id} for row in rows]
