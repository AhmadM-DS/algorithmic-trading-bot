from datetime import date, timedelta

import pytest

from storage.watchlist import get_popular_tickers, get_inactive_tickers
from watchlist.builder import build_watchlist

DAY_1 = date(2026, 10, 1)

def add_ticker(conn, ticker, days, pnls=(), is_active=1):
    """A ticker that appeared in the screener on `days` days and has closed trades with `pnls`"""
    ticker_id = conn.execute("INSERT INTO tickers (ticker, first_seen, is_active) OUTPUT INSERTED.ticker_id "
                             "VALUES (?, ?, ?)", (ticker, DAY_1, is_active)).fetchone()[0]
    for d in range(days):
        conn.execute("INSERT INTO watchlist_history ([date], [source], selected, ticker_id) VALUES (?, 'g', 1, ?)",
                     (DAY_1 + timedelta(days=d), ticker_id))
    strategy_id = conn.execute("SELECT TOP 1 strategy_id FROM strategies").fetchone()[0]
    for pnl in pnls:
        conn.execute("INSERT INTO positions (time_frame, holding_type, opened_at, closed_at, [status], entry_quantity, "
                     "avg_entry_price, realized_pnl, exit_reason, strategy_id, ticker_id) "
                     "VALUES ('15Min', 'day', '2026-10-01', '2026-10-01', 'closed', 1, 1, ?, 'take_profit', ?, ?)",
                     (pnl, strategy_id, ticker_id))

def set_override(admin_conn, ticker, value):
    """fill_override can only be changed as admin, so step out of the bot user and back"""
    admin_conn.execute("REVERT;")
    admin_conn.execute("UPDATE tickers SET fill_override = ? WHERE ticker = ?", (value, ticker))
    admin_conn.execute("EXECUTE AS USER = 'test_bot';")

def test_ranked_by_days_appeared(bot_conn):
    add_ticker(bot_conn, "FEW", 2)
    add_ticker(bot_conn, "MANY", 5)
    assert get_popular_tickers(bot_conn, 20, 3) == ["MANY", "FEW"]

def test_one_lucky_trade_does_not_break_ties(bot_conn):
    add_ticker(bot_conn, "AAA", 2)
    add_ticker(bot_conn, "LUCKY", 2, pnls=[100])
    assert get_popular_tickers(bot_conn, 20, 3) == ["AAA", "LUCKY"]

def test_profitable_trades_break_ties_after_min_trades(bot_conn):
    add_ticker(bot_conn, "AAA", 2, pnls=[5, -1, -1])
    add_ticker(bot_conn, "ZZZ", 2, pnls=[1, 1, 1])
    assert get_popular_tickers(bot_conn, 20, 3) == ["ZZZ", "AAA"]

def test_net_loss_after_min_trades_is_blacklisted(bot_conn):
    add_ticker(bot_conn, "LOSER", 9, pnls=[5, -20, -1])
    add_ticker(bot_conn, "OK", 1)
    assert get_popular_tickers(bot_conn, 20, 3) == ["OK"]

def test_net_loss_before_min_trades_is_not_blacklisted(bot_conn):
    add_ticker(bot_conn, "EARLY", 2, pnls=[-50])
    assert get_popular_tickers(bot_conn, 20, 3) == ["EARLY"]

def test_manual_blacklist_and_allow(bot_conn):
    add_ticker(bot_conn, "FORCED", 5, pnls=[50, 50, 50])
    add_ticker(bot_conn, "SAVED", 3, pnls=[-10, -10, -10])
    set_override(bot_conn, "FORCED", 0)
    set_override(bot_conn, "SAVED", 1)
    assert get_popular_tickers(bot_conn, 20, 3) == ["SAVED"]

def test_inactive_left_out(bot_conn):
    add_ticker(bot_conn, "DEAD", 7, is_active=0)
    add_ticker(bot_conn, "LIVE", 1)
    assert get_popular_tickers(bot_conn, 20, 3) == ["LIVE"]
    assert get_inactive_tickers(bot_conn) == {"DEAD"}

def test_limit(bot_conn):
    for i in range(5):
        add_ticker(bot_conn, f"T{i}", i + 1)
    assert len(get_popular_tickers(bot_conn, 3, 3)) == 3

def test_build_watchlist_screener_first_and_saves_hits(bot_conn):
    add_ticker(bot_conn, "GME", 5)
    add_ticker(bot_conn, "AMC", 3)
    final = build_watchlist(bot_conn, ["KTTA", "GME"], date(2026, 11, 2), "biggest-gainers", 3, 3)
    assert final == ["KTTA", "GME", "AMC"]
    hits = bot_conn.execute("SELECT t.ticker, wh.selected FROM watchlist_history wh JOIN tickers t "
                            "ON t.ticker_id = wh.ticker_id WHERE wh.[date] = '2026-11-02' ORDER BY t.ticker").fetchall()
    assert [(h.ticker, h.selected) for h in hits] == [("GME", True), ("KTTA", True)]

def test_build_watchlist_hit_over_cap_saved_as_not_selected(bot_conn):
    final = build_watchlist(bot_conn, ["A", "B", "C"], date(2026, 11, 2), "biggest-gainers", 3, 2)
    assert final == ["A", "B"]
    selected = bot_conn.execute("SELECT t.ticker FROM watchlist_history wh JOIN tickers t ON t.ticker_id = wh.ticker_id "
                                "WHERE wh.selected = 0").fetchall()
    assert [r.ticker for r in selected] == ["C"]

def test_build_watchlist_twice_same_day(bot_conn, caplog):
    caplog.set_level("INFO", logger="routine")
    build_watchlist(bot_conn, ["KTTA"], date(2026, 11, 2), "biggest-gainers", 3, 20)
    build_watchlist(bot_conn, ["KTTA"], date(2026, 11, 2), "biggest-gainers", 3, 20)
    assert "0 hits saved, 1 duplicates" in caplog.text
