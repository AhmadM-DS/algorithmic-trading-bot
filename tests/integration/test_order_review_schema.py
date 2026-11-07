"""
test_order_review_schema.py
Integration tests for migration 009: E2's skip codes and the order_reviews table (ticket E2-1's acceptance criteria)
"""

#Standard Library
from datetime import datetime, timedelta

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from risk_samples import add_signal, add_strategy, db_now

CHECKED_AT = datetime(2026, 11, 9, 15, 0, 5)

def insert_review(conn, signal_id, signal_price=10, check_price=10.2, check_price_at=CHECKED_AT, price_feed="iex",
                  price_move=0.02, max_price_move=0.01):
    """Save one review as the bot"""
    conn.execute("INSERT INTO order_reviews (signal_id, signal_price, check_price, check_price_at, price_feed, "
                 "price_move, max_price_move) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (signal_id, signal_price, check_price, check_price_at, price_feed, price_move, max_price_move))

def new_signal(conn) -> int:
    return add_signal(conn, add_strategy(conn), db_now(conn))

def test_e2_skip_codes_are_seeded(bot_conn):
    """Seed the six codes exactly as the ticket lists them"""

    rows = bot_conn.execute("SELECT skip_reason_id, code, [description], [priority] FROM skip_reasons "
                            "WHERE skip_reason_id BETWEEN 18 AND 23 ORDER BY skip_reason_id").fetchall()

    assert [tuple(row) for row in rows] == [
        (18, "market_closed", "Market is closed", 170),
        (19, "too_late_to_buy", "Too close to the close for a new buy", 180),
        (20, "not_tradable", "Alpaca can't trade this ticker", 190),
        (21, "open_order", "An order for this is already out", 200),
        (22, "stale_price", "No recent trade to check the price against", 210),
        (23, "price_moved", "Price moved too far since the signal", 220),
    ]

def test_review_saves_every_column(bot_conn):
    """Save a full review as the bot and read the same numbers back"""
    signal_id = new_signal(bot_conn)

    insert_review(bot_conn, signal_id, price_move=-0.054321)

    row = bot_conn.execute("SELECT * FROM order_reviews WHERE signal_id = ?", signal_id).fetchone()
    assert (float(row.signal_price), float(row.check_price), row.check_price_at, row.price_feed,
            float(row.price_move), float(row.max_price_move)) == (10, 10.2, CHECKED_AT, "iex", -0.054321, 0.01)

def test_review_without_a_recent_trade_is_saved(bot_conn):
    """Save a review whose check price, its time and the move are all missing"""
    signal_id = new_signal(bot_conn)

    insert_review(bot_conn, signal_id, check_price=None, check_price_at=None, price_move=None)

    assert bot_conn.execute("SELECT COUNT(*) FROM order_reviews WHERE signal_id = ?", signal_id).fetchone()[0] == 1

def test_review_needs_an_existing_signal(bot_conn):
    with pytest.raises(pyodbc.IntegrityError, match="fk_order_reviews_signal_id"):
        insert_review(bot_conn, 999999)

def test_second_review_of_a_signal_is_refused(bot_conn):
    signal_id = new_signal(bot_conn)
    insert_review(bot_conn, signal_id)

    with pytest.raises(pyodbc.IntegrityError, match="uq_order_reviews_signal_id"):
        insert_review(bot_conn, signal_id)

@pytest.mark.parametrize("column, value, constraint", [
    ("signal_price", 0, "ck_order_reviews_signal_price"),
    ("max_price_move", 0, "ck_order_reviews_max_price_move"),
    ("check_price", 0, "ck_order_reviews_check_price"),
    ("price_feed", "otc", "ck_order_reviews_price_feed"),
])
def test_invalid_values_are_refused(bot_conn, column, value, constraint):
    """Refuse a zero price or limit, and a feed other than sip / iex"""
    signal_id = new_signal(bot_conn)

    with pytest.raises(pyodbc.IntegrityError, match=constraint):
        insert_review(bot_conn, signal_id, **{column: value})

@pytest.mark.parametrize("missing", [("check_price",), ("check_price_at",), ("price_move",),
                                     ("check_price", "check_price_at")])
def test_check_price_its_time_and_move_go_together(bot_conn, missing):
    """Refuse a review with only some of the check price, its time and the move"""
    signal_id = new_signal(bot_conn)

    with pytest.raises(pyodbc.IntegrityError, match="ck_order_reviews_check_price_check_price_at_price_move"):
        insert_review(bot_conn, signal_id, **{column: None for column in missing})

def test_reviewed_at_defaults_to_utc_now(bot_conn):
    signal_id = new_signal(bot_conn)
    before = db_now(bot_conn)

    insert_review(bot_conn, signal_id)

    reviewed_at = bot_conn.execute("SELECT reviewed_at FROM order_reviews WHERE signal_id = ?", signal_id).fetchone()[0]
    assert before - timedelta(seconds=1) <= reviewed_at <= db_now(bot_conn) + timedelta(seconds=1)

def test_prices_and_fractions_use_agreed_types(bot_conn):
    """Store prices like every other price (19, 4) and moves with at least 6 decimal places"""

    rows = bot_conn.execute("SELECT COLUMN_NAME, NUMERIC_PRECISION, NUMERIC_SCALE FROM INFORMATION_SCHEMA.COLUMNS "
                            "WHERE TABLE_NAME = 'order_reviews' AND DATA_TYPE = 'decimal'").fetchall()
    types = {row.COLUMN_NAME: (row.NUMERIC_PRECISION, row.NUMERIC_SCALE) for row in rows}

    assert types["signal_price"] == types["check_price"] == (19, 4)
    assert min(types["price_move"][1], types["max_price_move"][1]) >= 6

@pytest.mark.parametrize("statement", ["UPDATE order_reviews SET price_feed = price_feed", "DELETE FROM order_reviews"])
def test_bot_cannot_change_or_delete_reviews(bot_conn, statement):
    """Keep reviews append-only for the bot, like risk_decisions"""
    insert_review(bot_conn, new_signal(bot_conn))

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute(statement)
