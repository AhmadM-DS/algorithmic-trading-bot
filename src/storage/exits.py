"""
exits.py
Read what closing a position needs: open positions to close, a position's orders and open buys
"""

#Local Imports
from storage.orders import DONE_STATUSES

POSITION_COLUMNS = ("v.position_id, v.strategy_id, v.strategy, v.ticker_id, v.ticker, v.holding_type, v.opened_at, "
                    "v.avg_entry_price, v.shares_held")

def _rows(cursor) -> list:
    """Return every fetched row as a dict of its columns"""
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]

def get_positions_by_holding_type(conn, holding_types: list) -> list:
    """Return the open positions of these holding types, oldest first

    Parameters:
        conn (Connection): An open database connection
        holding_types (list): e.g. ["day"]; empty returns nothing

    Returns:
        A list of {"position_id", "strategy_id", "strategy", "ticker_id", "ticker", "holding_type", "opened_at",
        "avg_entry_price", "shares_held"}; opened_at is naive UTC, shares_held is the database's count
    """
    if not holding_types:
        return []
    placeholders = ", ".join("?" * len(holding_types))
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT {POSITION_COLUMNS} FROM v_open_positions v WHERE v.holding_type IN ({placeholders}) "
        "ORDER BY v.opened_at, v.position_id",
        tuple(holding_types),
    )
    return _rows(cursor)

def get_open_position(conn, position_id: int) -> dict | None:
    """Return one open position, or None if it's closed or doesn't exist

    Parameters:
        conn (Connection): An open database connection
        position_id (int): The position's row

    Returns:
        The same dict as get_positions_by_holding_type, or None
    """
    cursor = conn.cursor()
    cursor.execute(f"SELECT {POSITION_COLUMNS} FROM v_open_positions v WHERE v.position_id = ?", (position_id,))
    rows = _rows(cursor)
    return rows[0] if rows else None

def get_closing_positions(conn) -> list:
    """Return the open positions the bot has already tried to sell, with the reason of its latest try

    "Tried to sell" = the position has a sell order that isn't a bracket leg and isn't manual, so a close that
    failed (or is still filling) is found again after a restart.

    Parameters:
        conn (Connection): An open database connection

    Returns:
        The same dicts as get_positions_by_holding_type plus "last_exit_reason", oldest position first
    """
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT {POSITION_COLUMNS}, s.exit_reason AS last_exit_reason FROM v_open_positions v "
        "CROSS APPLY (SELECT TOP 1 o.exit_reason FROM orders o WHERE o.position_id = v.position_id "
        "AND o.side = 'sell' AND o.parent_order_id IS NULL AND o.exit_reason <> 'manual' "
        "ORDER BY o.order_id DESC) s "
        "ORDER BY v.opened_at, v.position_id",
    )
    return _rows(cursor)

def get_position_orders(conn, position_id: int) -> list:
    """Return every order linked to a position: its buy, its bracket legs and any sells

    Parameters:
        conn (Connection): An open database connection
        position_id (int): The position's row

    Returns:
        A list of {"order_id", "client_order_id", "alpaca_order_id", "side", "order_type", "status",
        "requested_quantity", "filled_quantity", "parent_order_id", "exit_reason"}, oldest first
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT order_id, client_order_id, alpaca_order_id, side, order_type, [status] AS status, requested_quantity, "
        "filled_quantity, parent_order_id, exit_reason FROM orders WHERE position_id = ? ORDER BY order_id",
        (position_id,),
    )
    return _rows(cursor)

def get_open_buys(conn, holding_types: list) -> list:
    """Return the buy orders not done yet whose holding type is one of these, e.g. ["day"]

    The holding type is the signal's, or the strategy's default for a buy without a signal, so a manual buy
    (the manual strategy is swing) is never included.

    Parameters:
        conn (Connection): An open database connection
        holding_types (list): Holding types to include; empty returns nothing

    Returns:
        A list of {"order_id", "client_order_id", "alpaca_order_id", "status", "ticker", "strategy"}, oldest first
    """
    if not holding_types:
        return []
    done = ", ".join("?" * len(DONE_STATUSES))
    wanted = ", ".join("?" * len(holding_types))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT o.order_id, o.client_order_id, o.alpaca_order_id, o.[status] AS status, t.ticker, s.strategy "
        "FROM orders o JOIN tickers t ON t.ticker_id = o.ticker_id JOIN strategies s ON s.strategy_id = o.strategy_id "
        "LEFT JOIN signals sg ON sg.signal_id = o.signal_id "
        f"WHERE o.side = 'buy' AND o.parent_order_id IS NULL AND o.[status] NOT IN ({done}) "
        f"AND COALESCE(sg.holding_type, s.default_holding_type) IN ({wanted}) ORDER BY o.order_id",
        (*DONE_STATUSES, *holding_types),
    )
    return _rows(cursor)
