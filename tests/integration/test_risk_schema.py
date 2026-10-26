"""
test_risk_schema.py
Integration tests for migration 005: skip reasons, risk decisions, their grants and the budget trigger
"""

#Standard Library
from datetime import date, datetime

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from storage.watchlist import get_or_create_ticker

AGREED_PRIORITY = ["shadow", "strategy_off", "kill_switch", "audit_mismatch", "drawdown_limit", "daily_halt",
                   "max_leverage", "buying_power", "budget_exhausted", "max_positions", "max_per_ticker",
                   "max_positions_per_ticker", "cooldown", "zero_quantity", "max_order_size", "nothing_to_sell"]
"""Every skip code in the priority order agreed in the R1 decisions"""

def as_admin(conn, sql, params=()):
    """Run one statement as the admin (the bot can't change strategies), then switch back to the bot"""
    conn.execute("REVERT;")
    conn.execute(sql, params)
    conn.execute("EXECUTE AS USER = 'test_bot';")

def reason_id(conn, code):
    """Return a skip code's id"""
    return conn.execute("SELECT skip_reason_id FROM skip_reasons WHERE code = ?", code).fetchone()[0]

def strategy_id(conn, name="manual"):
    """Return a strategy row's id"""
    return conn.execute("SELECT strategy_id FROM strategies WHERE strategy = ?", name).fetchone()[0]

def insert_signal(conn, taken, primary_skip_reason_id):
    """Insert one signal as the bot and return its id"""
    ticker_id = get_or_create_ticker(conn, "AAPL", date(2026, 10, 26))
    return conn.execute(
        "INSERT INTO signals (side, time_frame, holding_type, quantity, reason, generated_at, taken, [source], "
        "strategy_version, git_commit, market_data_plan, data_feed, strategy_id, ticker_id, primary_skip_reason_id) "
        "OUTPUT INSERTED.signal_id "
        "VALUES ('buy', '15Min', 'day', 5, 'test', ?, ?, 'live', '1.0.0', 'abc123', 'delayed', 'sip', ?, ?, ?)",
        (datetime(2026, 10, 26, 14, 15), taken, strategy_id(conn), ticker_id, primary_skip_reason_id),
    ).fetchone()[0]

def insert_risk_decision(conn, signal_id):
    """Insert one risk decision as the bot and return its id"""
    return conn.execute(
        "INSERT INTO risk_decisions (signal_id, sizer, sized_quantity, equity, buying_power, trading_budget, "
        "account_exposure, strategy_exposure, ticker_exposure, open_positions, shares_held, broker_shares) "
        "OUTPUT INSERTED.risk_decision_id "
        "VALUES (?, 'fixed_budget:1.0.0', 5, 1000, 1000, 250, 400, 200, 0, 4, 0, 0)",
        signal_id,
    ).fetchone()[0]

def insert_parameter(conn, risk_decision_id, proposed, fell_back):
    """Insert one parameter row for a risk decision as the bot"""
    conn.execute(
        "INSERT INTO risk_decision_parameters (risk_decision_id, [name], [provider], proposed, used, "
        "clamped, rate_limited, fell_back) VALUES (?, 'position_fraction', 'static:1.0.0', ?, 0.2, 0, 0, ?)",
        (risk_decision_id, proposed, fell_back),
    )

def budget_events(conn, strategy):
    """Return the details of every budget_changed event for a strategy"""
    rows = conn.execute("SELECT details FROM bot_events WHERE event_type = 'budget_changed' AND strategy_id = ?",
                        strategy).fetchall()
    return [row.details for row in rows]

def test_skip_reasons_follow_agreed_priority(bot_conn):
    """Seed every skip code in the agreed priority order"""

    rows = bot_conn.execute("SELECT code FROM skip_reasons ORDER BY [priority]").fetchall()

    assert [row.code for row in rows] == AGREED_PRIORITY

def test_bot_cannot_add_skip_reasons(bot_conn):
    """Keep the skip code list for migrations only"""

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute("INSERT INTO skip_reasons VALUES (99, 'test', 'test', 999)")

def test_skipped_signal_saves_primary_reason_and_every_failure(bot_conn):
    """Save a skipped signal's primary reason on the signal and each failure in the bridge table"""
    leverage, budget = reason_id(bot_conn, "max_leverage"), reason_id(bot_conn, "budget_exhausted")
    signal_id = insert_signal(bot_conn, taken=0, primary_skip_reason_id=leverage)

    for failed in (leverage, budget):
        bot_conn.execute("INSERT INTO signal_skip_reasons (signal_id, skip_reason_id) VALUES (?, ?)", (signal_id, failed))

    saved = bot_conn.execute("SELECT COUNT(*) FROM signal_skip_reasons WHERE signal_id = ?", signal_id).fetchone()[0]
    assert saved == 2

def test_skipped_signal_needs_primary_reason(bot_conn):
    """Reject a skipped signal with no primary skip reason"""

    with pytest.raises(pyodbc.IntegrityError, match="ck_signals_taken_primary_skip_reason"):
        insert_signal(bot_conn, taken=0, primary_skip_reason_id=None)

def test_taken_signal_cannot_have_primary_reason(bot_conn):
    """Reject a taken signal that also has a skip reason"""

    with pytest.raises(pyodbc.IntegrityError, match="ck_signals_taken_primary_skip_reason"):
        insert_signal(bot_conn, taken=1, primary_skip_reason_id=reason_id(bot_conn, "shadow"))

def test_unknown_skip_reason_is_rejected(bot_conn):
    """Reject a primary skip reason that isn't in the lookup table, so typos can't become new reasons"""

    with pytest.raises(pyodbc.IntegrityError, match="fk_signals_primary_skip_reason_id"):
        insert_signal(bot_conn, taken=0, primary_skip_reason_id=999)

def test_bot_cannot_change_saved_failures(bot_conn):
    """Keep signal_skip_reasons append-only for the bot"""

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute("UPDATE signal_skip_reasons SET skip_reason_id = 1 WHERE 1 = 0")

def test_bot_cannot_delete_saved_failures(bot_conn):
    """Keep signal_skip_reasons append-only for the bot"""

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute("DELETE FROM signal_skip_reasons WHERE 1 = 0")

def test_risk_decision_and_parameters_are_saved(bot_conn):
    """Save one risk decision with its parameters as the bot"""
    decision_id = insert_risk_decision(bot_conn, insert_signal(bot_conn, taken=1, primary_skip_reason_id=None))

    insert_parameter(bot_conn, decision_id, proposed=0.2, fell_back=0)

    saved = bot_conn.execute("SELECT used FROM risk_decision_parameters WHERE risk_decision_id = ?", decision_id).fetchone()
    assert saved.used == pytest.approx(0.2)

def test_one_risk_decision_per_signal(bot_conn):
    """Reject a second risk decision for the same signal"""
    signal_id = insert_signal(bot_conn, taken=1, primary_skip_reason_id=None)
    insert_risk_decision(bot_conn, signal_id)

    with pytest.raises(pyodbc.IntegrityError, match="uq_risk_decisions_signal_id"):
        insert_risk_decision(bot_conn, signal_id)

def test_fallback_parameter_has_no_proposal(bot_conn):
    """Reject a fallback row that still has a proposed value"""
    decision_id = insert_risk_decision(bot_conn, insert_signal(bot_conn, taken=1, primary_skip_reason_id=None))

    with pytest.raises(pyodbc.IntegrityError, match="ck_risk_decision_parameters_fell_back"):
        insert_parameter(bot_conn, decision_id, proposed=0.4, fell_back=1)

def test_fallback_parameter_without_proposal_is_saved(bot_conn):
    """Save a fallback row with an empty proposal (NaN in Python)"""
    decision_id = insert_risk_decision(bot_conn, insert_signal(bot_conn, taken=1, primary_skip_reason_id=None))

    insert_parameter(bot_conn, decision_id, proposed=None, fell_back=1)

    saved = bot_conn.execute("SELECT proposed FROM risk_decision_parameters WHERE risk_decision_id = ?", decision_id).fetchone()
    assert saved.proposed is None

def test_bot_cannot_change_risk_decisions(bot_conn):
    """Keep risk_decisions append-only for the bot"""

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute("UPDATE risk_decisions SET sized_quantity = 0 WHERE 1 = 0")

def test_bot_cannot_change_risk_parameters(bot_conn):
    """Keep risk_decision_parameters append-only for the bot"""

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute("DELETE FROM risk_decision_parameters WHERE 1 = 0")

def test_budget_change_sets_budget_set_at(bot_conn):
    """Set budget_set_at to now when the admin changes a budget"""
    manual = strategy_id(bot_conn)
    as_admin(bot_conn, "UPDATE strategies SET budget_set_at = '2020-01-01' WHERE strategy_id = ?", (manual,))

    as_admin(bot_conn, "UPDATE strategies SET budget = 500 WHERE strategy_id = ?", (manual,))

    set_at = bot_conn.execute("SELECT budget_set_at FROM strategies WHERE strategy_id = ?", manual).fetchone()[0]
    assert set_at > datetime(2020, 1, 1)

def test_budget_change_writes_bot_event(bot_conn):
    """Write a budget_changed event with the old and new budget"""
    manual = strategy_id(bot_conn)

    as_admin(bot_conn, "UPDATE strategies SET budget = 500 WHERE strategy_id = ?", (manual,))

    assert budget_events(bot_conn, manual) == ["Budget changed from 0.0000 to 500.0000"]

def test_same_budget_changes_nothing(bot_conn):
    """Leave budget_set_at alone and write no event when the budget is saved with the same value"""
    manual = strategy_id(bot_conn)
    as_admin(bot_conn, "UPDATE strategies SET budget_set_at = '2020-01-01' WHERE strategy_id = ?", (manual,))

    as_admin(bot_conn, "UPDATE strategies SET budget = budget WHERE strategy_id = ?", (manual,))

    set_at = bot_conn.execute("SELECT budget_set_at FROM strategies WHERE strategy_id = ?", manual).fetchone()[0]
    assert set_at == datetime(2020, 1, 1)
    assert budget_events(bot_conn, manual) == []

def test_other_column_change_does_not_touch_budget_set_at(bot_conn):
    """Leave budget_set_at alone when only the mode changes"""
    manual = strategy_id(bot_conn)
    as_admin(bot_conn, "UPDATE strategies SET budget_set_at = '2020-01-01' WHERE strategy_id = ?", (manual,))

    as_admin(bot_conn, "UPDATE strategies SET mode = 'live' WHERE strategy_id = ?", (manual,))

    set_at = bot_conn.execute("SELECT budget_set_at FROM strategies WHERE strategy_id = ?", manual).fetchone()[0]
    assert set_at == datetime(2020, 1, 1)

def test_multi_row_budget_change_writes_event_per_strategy(bot_conn):
    """Write one event per strategy whose budget changed in a single UPDATE"""
    manual, unknown = strategy_id(bot_conn, "manual"), strategy_id(bot_conn, "unknown")

    as_admin(bot_conn, "UPDATE strategies SET budget = 100 WHERE strategy IN ('manual', 'unknown')")

    assert len(budget_events(bot_conn, manual)) == 1
    assert len(budget_events(bot_conn, unknown)) == 1
