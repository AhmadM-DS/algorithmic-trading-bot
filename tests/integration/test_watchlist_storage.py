from datetime import date

import pyodbc
import pytest

from storage.watchlist import get_or_create_ticker, insert_watchlist_hit

DAY_1 = date(2026, 10, 5)
DAY_2 = date(2026, 10, 6)

def fetch_ticker(conn, ticker):
    return conn.execute("SELECT ticker_id, first_seen, is_active FROM tickers WHERE ticker = ?",
                        (ticker,)).fetchone()

def count_hits(conn, ticker):
    return conn.execute("SELECT COUNT(*) FROM watchlist_history wh "
                        "JOIN tickers t ON t.ticker_id = wh.ticker_id WHERE t.ticker = ?",
                        (ticker,)).fetchone()[0]

def test_new_ticker_is_created(bot_conn):
    ticker_id = get_or_create_ticker(bot_conn, "NVDA", DAY_1)
    row = fetch_ticker(bot_conn, "NVDA")
    assert row.ticker_id == ticker_id
    assert row.first_seen == DAY_1
    assert row.is_active

def test_existing_ticker_keeps_id_and_first_seen(bot_conn):
    first_id = get_or_create_ticker(bot_conn, "NVDA", DAY_1)
    second_id = get_or_create_ticker(bot_conn, "NVDA", DAY_2)
    assert first_id == second_id
    assert fetch_ticker(bot_conn, "NVDA").first_seen == DAY_1

def test_hit_is_saved(bot_conn):
    assert insert_watchlist_hit(bot_conn, "NVDA", DAY_1, "biggest-gainers", True)
    row = bot_conn.execute("SELECT [date], [source], selected FROM watchlist_history").fetchone()
    assert row.date == DAY_1
    assert row.source == "biggest-gainers"
    assert row.selected

def test_duplicate_hit_returns_false(bot_conn):
    assert insert_watchlist_hit(bot_conn, "NVDA", DAY_1, "biggest-gainers", True)
    assert not insert_watchlist_hit(bot_conn, "NVDA", DAY_1, "biggest-gainers", False)
    assert count_hits(bot_conn, "NVDA") == 1

def test_same_ticker_other_source_or_day_is_saved(bot_conn):
    assert insert_watchlist_hit(bot_conn, "NVDA", DAY_1, "biggest-gainers", True)
    assert insert_watchlist_hit(bot_conn, "NVDA", DAY_1, "most-active", True)
    assert insert_watchlist_hit(bot_conn, "NVDA", DAY_2, "biggest-gainers", True)
    assert count_hits(bot_conn, "NVDA") == 3

def test_other_integrity_errors_are_raised(bot_conn):
    with pytest.raises(pyodbc.IntegrityError):
        insert_watchlist_hit(bot_conn, "NVDA", DAY_1, None, True)
