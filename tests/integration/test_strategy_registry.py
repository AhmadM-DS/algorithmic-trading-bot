"""
test_strategy_registry.py
Integration tests for strategies/registry.py against noctis_test
"""

#Standard Library
from datetime import date, datetime

#Local Imports
from strategies.base import Strategy
from strategies.registry import load_strategies, skip_alert
from storage.strategies import get_strategy_rows, register_strategy
from storage.watchlist import get_or_create_ticker

DELAYED_PROFILE = {"feed": "sip", "lag_minutes": 15, "min_time_frame_minutes": 15}

class RsiStrategy(Strategy):
    """Fake valid day strategy"""
    NAME = "rsi_test"
    TIME_FRAME = "15Min"
    DEFAULT_HOLDING_TYPE = "day"
    LOOKBACK_WINDOW = 20
    VERSION = "1.0.0"

    def generate_signal(self, ticker, candles, position):
        return None

class EmaStrategy(RsiStrategy):
    """Fake second valid day strategy"""
    NAME = "ema_test"

class BrokenStrategy(RsiStrategy):
    """Fake strategy that fails check_settings"""
    NAME = "broken_test"
    TIME_FRAME = "5Min"

class CopiedNameStrategy(RsiStrategy):
    """Fake strategy that reuses RsiStrategy's NAME"""

def as_admin(conn, sql, params=()):
    """Run one statement as the admin (the bot has no UPDATE on strategies), then switch back"""
    conn.execute("REVERT;")
    conn.execute(sql, params)
    conn.execute("EXECUTE AS USER = 'test_bot';")

def skip_events(conn):
    """Return every strategy_skipped event"""
    return conn.execute("SELECT details, strategy_id FROM bot_events "
                        "WHERE event_type = 'strategy_skipped' ORDER BY bot_event_id").fetchall()

def test_new_strategy_is_registered_and_can_run(bot_conn):
    """Register a new strategy (shadow, budget 0) and include it in runnable"""
    runnable, skipped = load_strategies(bot_conn, [RsiStrategy()], DELAYED_PROFILE)

    row = get_strategy_rows(bot_conn)["rsi_test"]

    assert list(runnable) == ["rsi_test"] and skipped == []
    assert row["mode"] == "shadow" and row["budget"] == 0

def test_matching_strategy_runs_without_registering_again(bot_conn):
    """Run a strategy whose class matches its row, without a second insert"""
    load_strategies(bot_conn, [RsiStrategy()], DELAYED_PROFILE)

    runnable, skipped = load_strategies(bot_conn, [RsiStrategy()], DELAYED_PROFILE)

    assert list(runnable) == ["rsi_test"] and skipped == []
    assert bot_conn.execute("SELECT COUNT(*) FROM strategies WHERE strategy = 'rsi_test'").fetchone()[0] == 1

def test_row_mismatch_skips_only_that_strategy(bot_conn):
    """Skip a strategy whose row has a different time frame and keep running the others"""
    load_strategies(bot_conn, [RsiStrategy(), EmaStrategy()], DELAYED_PROFILE)
    as_admin(bot_conn, "UPDATE strategies SET time_frame = '30Min' WHERE strategy = 'rsi_test'")

    runnable, skipped = load_strategies(bot_conn, [RsiStrategy(), EmaStrategy()], DELAYED_PROFILE)

    assert list(runnable) == ["ema_test"]
    assert skipped[0]["name"] == "rsi_test"
    assert skipped[0]["reason"] == "TIME_FRAME is '15Min' in the class but '30Min' in the strategies table"

def test_every_row_difference_is_reported(bot_conn):
    """Report a time frame and a holding type difference together"""
    load_strategies(bot_conn, [RsiStrategy()], DELAYED_PROFILE)
    as_admin(bot_conn, "UPDATE strategies SET time_frame = '30Min', default_holding_type = 'swing' "
                       "WHERE strategy = 'rsi_test'")

    runnable, skipped = load_strategies(bot_conn, [RsiStrategy()], DELAYED_PROFILE)

    assert "TIME_FRAME is '15Min'" in skipped[0]["reason"]
    assert "DEFAULT_HOLDING_TYPE is 'day'" in skipped[0]["reason"]

def test_skip_saves_bot_event_with_strategy_id(bot_conn):
    """Save one strategy_skipped event pointing at the skipped strategy's row"""
    load_strategies(bot_conn, [RsiStrategy()], DELAYED_PROFILE)
    as_admin(bot_conn, "UPDATE strategies SET time_frame = '30Min' WHERE strategy = 'rsi_test'")

    load_strategies(bot_conn, [RsiStrategy()], DELAYED_PROFILE)

    events = skip_events(bot_conn)
    assert len(events) == 1
    assert events[0].strategy_id == get_strategy_rows(bot_conn)["rsi_test"]["strategy_id"]
    assert events[0].details.startswith("rsi_test: TIME_FRAME is '15Min'")

def test_failed_check_settings_skips_without_registering(bot_conn):
    """Skip a strategy that fails check_settings and don't give it a row"""
    runnable, skipped = load_strategies(bot_conn, [RsiStrategy(), BrokenStrategy()], DELAYED_PROFILE)

    assert list(runnable) == ["rsi_test"]
    assert skipped[0]["name"] == "broken_test"
    assert "TIME_FRAME '5Min' is shorter than the market data plan's minimum" in skipped[0]["reason"]
    assert "broken_test" not in get_strategy_rows(bot_conn)
    assert skip_events(bot_conn)[0].strategy_id is None

def test_shared_name_skips_both_classes(bot_conn):
    """Skip every class that shares a NAME, so two strategies never share one row"""
    runnable, skipped = load_strategies(bot_conn, [RsiStrategy(), CopiedNameStrategy()], DELAYED_PROFILE)

    assert runnable == {}
    assert [skip["name"] for skip in skipped] == ["rsi_test", "rsi_test"]
    assert "used by more than one strategy class" in skipped[0]["reason"]

def test_shared_name_reason_lists_every_class(bot_conn):
    """Name every class that shares the NAME, so the alert says which classes to fix"""
    runnable, skipped = load_strategies(bot_conn, [RsiStrategy(), CopiedNameStrategy()], DELAYED_PROFILE)

    assert skipped[0]["reason"] == "NAME 'rsi_test' is used by more than one strategy class (RsiStrategy, CopiedNameStrategy)"

def test_live_row_without_class_is_reported(bot_conn):
    """Report a live row that no strategy class uses"""
    register_strategy(bot_conn, "deleted_test", "15Min", "day")
    as_admin(bot_conn, "UPDATE strategies SET mode = 'live' WHERE strategy = 'deleted_test'")

    runnable, skipped = load_strategies(bot_conn, [RsiStrategy()], DELAYED_PROFILE)

    assert list(runnable) == ["rsi_test"]
    assert skipped[0]["name"] == "deleted_test"
    assert skipped[0]["reason"] == "is in live mode in the strategies table but no strategy class has this name"

def test_shadow_row_without_class_is_reported(bot_conn):
    """Report a shadow row that no strategy class uses"""
    register_strategy(bot_conn, "deleted_test", "15Min", "day")

    runnable, skipped = load_strategies(bot_conn, [], DELAYED_PROFILE)

    assert [skip["name"] for skip in skipped] == ["deleted_test"]
    assert skipped[0]["reason"].startswith("is in shadow mode")

def test_off_rows_without_class_are_ignored(bot_conn):
    """Leave off rows with no class alone (e.g. the manual and unknown seed rows)"""
    runnable, skipped = load_strategies(bot_conn, [], DELAYED_PROFILE)

    assert runnable == {} and skipped == []

def test_skip_counts_open_positions(bot_conn):
    """Count a skipped strategy's open positions so the alert can warn about them"""
    load_strategies(bot_conn, [RsiStrategy()], DELAYED_PROFILE)
    strategy_id = get_strategy_rows(bot_conn)["rsi_test"]["strategy_id"]
    ticker_id = get_or_create_ticker(bot_conn, "AAPL", date(2026, 10, 19))
    bot_conn.execute("INSERT INTO positions (time_frame, holding_type, opened_at, [status], entry_quantity, "
                     "avg_entry_price, strategy_id, ticker_id) VALUES ('15Min', 'day', ?, 'open', 10, 100, ?, ?)",
                     (datetime(2026, 10, 19, 14, 0), strategy_id, ticker_id))
    as_admin(bot_conn, "UPDATE strategies SET time_frame = '30Min' WHERE strategy = 'rsi_test'")

    runnable, skipped = load_strategies(bot_conn, [RsiStrategy()], DELAYED_PROFILE)

    assert skipped[0]["open_positions"] == 1

def test_skip_alert_lists_every_skip_and_open_positions():
    """Build one message naming every skipped strategy and warning about open positions"""
    skipped = [{"name": "rsi_test", "reason": "TIME_FRAME is '15Min' in the class but '30Min' in the strategies table",
                "open_positions": 2},
               {"name": "broken_test", "reason": "bad settings", "open_positions": 0}]

    message = skip_alert(skipped)

    assert message.startswith("2 strategy(s) skipped at startup. The others are running.")
    assert "- rsi_test: TIME_FRAME is '15Min'" in message
    assert "It holds 2 open position(s): its sells won't run until this is fixed." in message
    assert "- broken_test: bad settings\n" in message

def test_skip_alert_is_none_when_nothing_skipped():
    """Return None so the caller sends nothing when every strategy loaded"""
    assert skip_alert([]) is None
