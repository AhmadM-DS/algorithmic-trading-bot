"""
order_reviews.py
Save what the pre-order review checked a buy's price against
"""

#Standard Library
from datetime import datetime

#Local Imports
from logger import db_log

def insert_order_review(conn, signal_id: int, *, signal_price: float, check_price: float | None,
                        check_price_at: datetime | None, price_feed: str, price_move: float | None,
                        max_price_move: float):
    """Save one reviewed buy's price check

    check_price, check_price_at and price_move are all None when the ticker had no recent trade. Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        signal_id (int): The saved buy signal
        signal_price (float): The price the strategy decided on
        check_price (float | None): The latest real-time trade's price
        check_price_at (datetime | None): When that trade happened, naive UTC
        price_feed (str): "sip" or "iex"
        price_move (float | None): (check_price - signal_price) / signal_price
        max_price_move (float): The largest move allowed for this signal, as a fraction
    """
    conn.cursor().execute(
        "INSERT INTO order_reviews (signal_id, signal_price, check_price, check_price_at, price_feed, price_move, "
        "max_price_move) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (signal_id, signal_price, check_price, check_price_at, price_feed, price_move, max_price_move),
    )
    db_log.debug(f"order_reviews saved: signal_id {signal_id}")
