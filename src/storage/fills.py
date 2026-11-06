"""
fills.py
Read and write what the fill stream records: broker_events, trades, positions and the orders they update
"""

#Standard Library
from datetime import datetime
from decimal import Decimal

#Local Imports
from logger import db_log

FILL_EVENT_TYPES = ("fill", "partial_fill", "catch_up_fill")
FINAL_STATUSES = ("filled", "canceled", "expired", "rejected", "replaced")
BOT_STATUSES = ("submitting", "unknown", "not_sent")

def save_broker_event(conn, *, event_type: str, alpaca_order_id: str | None, client_order_id: str | None,
                      execution_id: str | None, ticker: str | None, event_at: datetime | None,
                      raw_json: str) -> int:
    """Save one event from Alpaca exactly as it arrived and return its broker_event_id

    Saved before anything else handles the event, so a failure later can't lose it. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        event_type (str): Alpaca's event ("fill", "canceled", ...) or "catch_up_fill" / "catch_up_status"
        alpaca_order_id (str | None): Alpaca's ID for the order
        client_order_id (str | None): The order's client_order_id, if the event has one
        execution_id (str | None): Alpaca's execution ID; on a fill, the fill's unique ID
        ticker (str | None): The ticker symbol
        event_at (datetime | None): When it happened by Alpaca's clock, naive UTC
        raw_json (str): The whole message as text

    Returns:
        The new broker_event_id as an int
    """
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO broker_events (alpaca_order_id, client_order_id, execution_id, event_type, ticker, event_at, raw_json) "
        "OUTPUT INSERTED.broker_event_id "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (alpaca_order_id, client_order_id, execution_id, event_type, ticker, event_at, raw_json),
    )
    broker_event_id = cursor.fetchone()[0]
    db_log.debug(f"broker_events saved: {event_type} for {alpaca_order_id} as {broker_event_id}")
    return broker_event_id

def fill_seen(conn, fill_id: str) -> bool:
    """Check whether a fill was already saved to broker_events, handled or not

    Parameters:
        conn (Connection): An open database connection
        fill_id (str): Alpaca's execution ID for the fill

    Returns:
        True if a fill event with that ID is saved
    """
    row = conn.cursor().execute(
        "SELECT TOP 1 1 FROM broker_events WHERE execution_id = ? AND event_type IN (?, ?, ?)",
        (fill_id, *FILL_EVENT_TYPES),
    ).fetchone()
    return row is not None

def trade_exists(conn, fill_id: str) -> bool:
    """Check whether a fill already has its trades row

    Parameters:
        conn (Connection): An open database connection
        fill_id (str): Alpaca's execution ID for the fill

    Returns:
        True if trades has a row with that alpaca_fill_id
    """
    row = conn.cursor().execute("SELECT 1 FROM trades WHERE alpaca_fill_id = ?", (fill_id,)).fetchone()
    return row is not None

def find_order_row(conn, alpaca_order_id: str | None, client_order_id: str | None) -> dict | None:
    """Find the bot's row for an order, by Alpaca's ID first, then by client_order_id

    client_order_id finds a buy whose Alpaca ID isn't saved yet (E1 saves the row before sending).

    Parameters:
        conn (Connection): An open database connection
        alpaca_order_id (str | None): Alpaca's ID for the order
        client_order_id (str | None): The order's client_order_id

    Returns:
        A dict of the row's columns plus "strategy" (the strategy's name), or None if neither ID matches
    """
    select = ("SELECT o.order_id, o.client_order_id, o.alpaca_order_id, o.side, o.order_type, o.[status], "
              "o.requested_quantity, o.filled_quantity, o.strategy_id, s.strategy, o.ticker_id, o.signal_id, "
              "o.position_id, o.parent_order_id, o.exit_reason "
              "FROM orders o JOIN strategies s ON s.strategy_id = o.strategy_id ")
    cursor = conn.cursor()
    row = None
    if alpaca_order_id is not None:
        row = cursor.execute(select + "WHERE o.alpaca_order_id = ?", (alpaca_order_id,)).fetchone()
    if row is None and client_order_id is not None:
        row = cursor.execute(select + "WHERE o.client_order_id = ?", (client_order_id,)).fetchone()
    if row is None:
        return None
    return {column[0]: value for column, value in zip(row.cursor_description, row)}

def update_order_from_broker(conn, order_id: int, alpaca_order_id: str, status: str, filled_quantity: int,
                             filled_price: Decimal | None):
    """Copy Alpaca's latest version onto an order, never moving it backwards

    The stream and the catch-up can deliver events out of order, so a final status (filled, canceled,
    expired, rejected, replaced) is never overwritten, filled_quantity never goes down, and a missing
    price keeps the saved one. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        order_id (int): The order's row
        alpaca_order_id (str): Alpaca's ID, saved if the row doesn't have it yet
        status (str): Alpaca's status, e.g. "filled"
        filled_quantity (int): Shares filled so far
        filled_price (Decimal | None): Alpaca's average fill price, None if unknown
    """
    conn.cursor().execute(
        "UPDATE orders SET "
        "alpaca_order_id = COALESCE(alpaca_order_id, ?), "
        f"[status] = CASE WHEN [status] IN ({', '.join('?' * len(FINAL_STATUSES))}) THEN [status] ELSE ? END, "
        "filled_price = CASE WHEN ? >= filled_quantity AND ? IS NOT NULL THEN ? ELSE filled_price END, "
        "filled_quantity = CASE WHEN ? > filled_quantity THEN ? ELSE filled_quantity END "
        "WHERE order_id = ?",
        (alpaca_order_id, *FINAL_STATUSES, status, filled_quantity, filled_price, filled_price,
         filled_quantity, filled_quantity, order_id),
    )
    db_log.debug(f"orders updated from Alpaca: order_id {order_id} reported {status}, {filled_quantity} filled")

def set_order_price_from_trades(conn, order_id: int):
    """Set an order's average fill price from its trades, for a fill that arrived without one

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        order_id (int): The order's row
    """
    conn.cursor().execute(
        "UPDATE orders SET filled_price = "
        "(SELECT SUM(quantity * fill_price) / SUM(quantity) FROM trades WHERE order_id = ?) "
        "WHERE order_id = ?",
        (order_id, order_id),
    )
    db_log.debug(f"orders.filled_price set from trades: order_id {order_id}")

def set_order_position(conn, order_id: int, position_id: int):
    """Link an order to the position it opened or closes

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        order_id (int): The order's row
        position_id (int): The position's row
    """
    conn.cursor().execute("UPDATE orders SET position_id = ? WHERE order_id = ?", (position_id, order_id))

def set_legs_position(conn, parent_order_id: int, position_id: int) -> int:
    """Link a buy's bracket legs to the position the buy opened

    Legs that already have a position are left alone. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        parent_order_id (int): The buy's order_id
        position_id (int): The position the buy opened

    Returns:
        How many legs were linked (0 if E1 hasn't saved them yet)
    """
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE orders SET position_id = ? WHERE parent_order_id = ? AND position_id IS NULL",
        (position_id, parent_order_id),
    )
    return cursor.rowcount

def get_order_position(conn, order_id: int) -> int | None:
    """Return the position an order is linked to

    Parameters:
        conn (Connection): An open database connection
        order_id (int): The order's row

    Returns:
        The position_id, or None if the order has none (or doesn't exist)
    """
    row = conn.cursor().execute("SELECT position_id FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    return None if row is None else row.position_id

def get_entry_defaults(conn, strategy_id: int, signal_id: int | None) -> tuple:
    """Return the time frame and holding type a new position takes

    From the signal that opened it, or from the strategy's defaults when there's no signal (manual trades).

    Parameters:
        conn (Connection): An open database connection
        strategy_id (int): The strategy that owns the position
        signal_id (int | None): The signal behind the buy, if any

    Returns:
        (time_frame, holding_type), e.g. ("15Min", "day")
    """
    row = conn.cursor().execute(
        "SELECT COALESCE(sg.time_frame, s.time_frame) AS time_frame, "
        "COALESCE(sg.holding_type, s.default_holding_type) AS holding_type "
        "FROM strategies s LEFT JOIN signals sg ON sg.signal_id = ? "
        "WHERE s.strategy_id = ?",
        (signal_id, strategy_id),
    ).fetchone()
    return row.time_frame, row.holding_type

def insert_position(conn, *, strategy_id: int, ticker_id: int, signal_id: int | None, time_frame: str,
                    holding_type: str, opened_at: datetime, quantity: int, price: Decimal) -> int:
    """Open a position from a buy's first fill and return its position_id

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        strategy_id (int): The strategy that owns it
        ticker_id (int): The ticker's id
        signal_id (int | None): The signal that opened it, if any
        time_frame (str): The time frame it trades on
        holding_type (str): "day" or "swing"
        opened_at (datetime): When the first share filled, naive UTC
        quantity (int): Shares in the first fill
        price (Decimal): The first fill's price

    Returns:
        The new position_id as an int
    """
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO positions (time_frame, holding_type, opened_at, [status], entry_quantity, avg_entry_price, "
        "strategy_id, ticker_id, signal_id) "
        "OUTPUT INSERTED.position_id "
        "VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?)",
        (time_frame, holding_type, opened_at, quantity, price, strategy_id, ticker_id, signal_id),
    )
    position_id = cursor.fetchone()[0]
    db_log.debug(f"positions opened: {position_id} with {quantity} @ {price}")
    return position_id

def add_to_position(conn, position_id: int, quantity: int, price: Decimal):
    """Add a later partial fill to a position's entry quantity and average entry price

    The average is weighted by shares: (old shares x old average + new shares x new price) / all shares.
    Both SET lines read the row as it was before the update. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        position_id (int): The position's row
        quantity (int): Shares in this fill
        price (Decimal): This fill's price
    """
    conn.cursor().execute(
        "UPDATE positions SET "
        "avg_entry_price = (entry_quantity * avg_entry_price + ? * ?) / (entry_quantity + ?), "
        "entry_quantity = entry_quantity + ? "
        "WHERE position_id = ?",
        (quantity, price, quantity, quantity, position_id),
    )

def get_position(conn, position_id: int) -> dict:
    """Return the columns of a position the fill stream needs

    Parameters:
        conn (Connection): An open database connection
        position_id (int): The position's row

    Returns:
        {"position_id", "status", "time_frame", "strategy_id", "ticker_id"}
    """
    row = conn.cursor().execute(
        "SELECT position_id, [status], time_frame, strategy_id, ticker_id FROM positions WHERE position_id = ?",
        (position_id,),
    ).fetchone()
    return {"position_id": row.position_id, "status": row.status, "time_frame": row.time_frame,
            "strategy_id": row.strategy_id, "ticker_id": row.ticker_id}

def insert_trade(conn, *, fill_id: str, side: str, quantity: int, filled_at: datetime, fill_price: Decimal,
                 time_frame: str, exit_reason: str | None, position_id: int, order_id: int) -> int:
    """Save one fill as a trades row and return its trade_id

    alpaca_fill_id is UNIQUE, so saving the same fill twice raises instead of double counting. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        fill_id (str): Alpaca's execution ID for the fill
        side (str): "buy" or "sell"
        quantity (int): Shares in this fill
        filled_at (datetime): When it filled, naive UTC
        fill_price (Decimal): This fill's price
        time_frame (str): The position's time frame
        exit_reason (str | None): Why a sell happened; None on buys
        position_id (int): The position it belongs to
        order_id (int): The order it filled

    Returns:
        The new trade_id as an int

    Raises:
        pyodbc.IntegrityError if the fill is already saved
    """
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO trades (alpaca_fill_id, side, quantity, filled_at, fill_price, time_frame, exit_reason, "
        "position_id, order_id) "
        "OUTPUT INSERTED.trade_id "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fill_id, side, quantity, filled_at, fill_price, time_frame, exit_reason, position_id, order_id),
    )
    trade_id = cursor.fetchone()[0]
    db_log.debug(f"trades saved: {side} {quantity} @ {fill_price} ({fill_id}) as {trade_id}")
    return trade_id

def get_position_totals(conn, position_id: int) -> dict:
    """Return a position's shares still held and the money in and out, calculated from its trades

    Parameters:
        conn (Connection): An open database connection
        position_id (int): The position's row

    Returns:
        {"shares_held": int, "bought": Decimal, "sold": Decimal}, all 0 if it has no trades
    """
    row = conn.cursor().execute(
        "SELECT COALESCE(SUM(CASE WHEN side = 'sell' THEN -quantity ELSE quantity END), 0) AS shares_held, "
        "COALESCE(SUM(CASE WHEN side = 'buy' THEN quantity * fill_price END), 0) AS bought, "
        "COALESCE(SUM(CASE WHEN side = 'sell' THEN quantity * fill_price END), 0) AS sold "
        "FROM trades WHERE position_id = ?",
        (position_id,),
    ).fetchone()
    return {"shares_held": row.shares_held, "bought": Decimal(row.bought), "sold": Decimal(row.sold)}

def close_position(conn, position_id: int, closed_at: datetime, exit_reason: str, realized_pnl: Decimal):
    """Mark an open position closed with when, why and its profit or loss

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        position_id (int): The position's row
        closed_at (datetime): When the last share was sold, naive UTC
        exit_reason (str): The closing sell's reason, e.g. "stop_loss"
        realized_pnl (Decimal): Money from sells minus money for buys

    Raises:
        LookupError if the position isn't open
    """
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE positions SET [status] = 'closed', closed_at = ?, exit_reason = ?, realized_pnl = ? "
        "WHERE position_id = ? AND [status] = 'open'",
        (closed_at, exit_reason, realized_pnl, position_id),
    )
    if cursor.rowcount != 1:
        raise LookupError(f"Expected to close 1 open position with position_id {position_id}, "
                          f"closed {cursor.rowcount}")
    db_log.debug(f"positions closed: {position_id} ({exit_reason}, {realized_pnl})")

def get_open_positions_for_ticker(conn, ticker_id: int) -> list:
    """Return a ticker's open positions with shares held, manual positions first, then oldest first

    The order is the order a manual sell takes shares from.

    Parameters:
        conn (Connection): An open database connection
        ticker_id (int): The ticker's id

    Returns:
        A list of {"position_id", "strategy", "shares_held"}
    """
    rows = conn.cursor().execute(
        "SELECT p.position_id, s.strategy, "
        "COALESCE(SUM(CASE WHEN t.side = 'sell' THEN -t.quantity ELSE t.quantity END), 0) AS shares_held "
        "FROM positions p "
        "JOIN strategies s ON s.strategy_id = p.strategy_id "
        "LEFT JOIN trades t ON t.position_id = p.position_id "
        "WHERE p.ticker_id = ? AND p.[status] = 'open' "
        "GROUP BY p.position_id, s.strategy, p.opened_at "
        "ORDER BY CASE WHEN s.strategy = 'manual' THEN 0 ELSE 1 END, p.opened_at, p.position_id",
        (ticker_id,),
    ).fetchall()
    return [{"position_id": row.position_id, "strategy": row.strategy, "shares_held": row.shares_held}
            for row in rows]

def get_unhandled_fills(conn) -> list:
    """Return fill events in broker_events that have no trades row yet, oldest first

    These are fills whose handling failed or is still waiting (e.g. for E1 to save the order row).

    Parameters:
        conn (Connection): An open database connection

    Returns:
        A list of {"broker_event_id", "event_type", "raw_json"}
    """
    rows = conn.cursor().execute(
        "SELECT e.broker_event_id, e.event_type, e.raw_json "
        "FROM broker_events e "
        "LEFT JOIN trades t ON t.alpaca_fill_id = e.execution_id "
        "WHERE e.event_type IN (?, ?, ?) AND t.trade_id IS NULL "
        "ORDER BY e.broker_event_id",
        FILL_EVENT_TYPES,
    ).fetchall()
    return [{"broker_event_id": row.broker_event_id, "event_type": row.event_type, "raw_json": row.raw_json}
            for row in rows]

def get_last_event_time(conn) -> datetime | None:
    """Return Alpaca's time of the newest saved event, where the next catch-up starts from

    Parameters:
        conn (Connection): An open database connection

    Returns:
        The latest event_at (naive UTC), or None if nothing is saved yet
    """
    return conn.cursor().execute("SELECT MAX(event_at) FROM broker_events").fetchone()[0]

def get_open_orders(conn) -> list:
    """Return orders Alpaca knows that aren't in a final status yet, for the catch-up to look up

    Orders still "submitting" / "unknown" / "not_sent" are left to E1's stuck-order sweep.

    Parameters:
        conn (Connection): An open database connection

    Returns:
        A list of {"order_id", "alpaca_order_id", "status", "filled_quantity", "ticker"}
    """
    excluded = FINAL_STATUSES + BOT_STATUSES
    rows = conn.cursor().execute(
        "SELECT o.order_id, o.alpaca_order_id, o.[status], o.filled_quantity, t.ticker "
        "FROM orders o JOIN tickers t ON t.ticker_id = o.ticker_id "
        f"WHERE o.alpaca_order_id IS NOT NULL AND o.[status] NOT IN ({', '.join('?' * len(excluded))}) "
        "ORDER BY o.order_id",
        excluded,
    ).fetchall()
    return [{"order_id": row.order_id, "alpaca_order_id": row.alpaca_order_id, "status": row.status,
             "filled_quantity": row.filled_quantity, "ticker": row.ticker} for row in rows]

def get_strategy_id(conn, strategy: str) -> int:
    """Return a strategy's id by name

    Parameters:
        conn (Connection): An open database connection
        strategy (str): The strategy's name, e.g. "manual"

    Returns:
        The strategy_id as an int

    Raises:
        LookupError if no strategy has that name
    """
    row = conn.cursor().execute("SELECT strategy_id FROM strategies WHERE strategy = ?", (strategy,)).fetchone()
    if row is None:
        raise LookupError(f"No strategy named {strategy!r}")
    return row.strategy_id
