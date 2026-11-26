"""
test_audit_schema.py
Integration tests for migration 011: audit_log's new columns and rules, audit_failures, cash_adjustments and the
audit_failure skip code
"""

#Standard Library
from datetime import date

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from risk_samples import as_admin

AUDIT_DATE = date(2026, 11, 24)

def insert_audit(conn, status="pass", not_run_reason=None, counts=0, share_mismatches=0, alpaca_cash=None,
                 expected_cash=None) -> int:
    """Save one audit_log row as the bot and return its id; counts fills every count column (None for not_run)"""
    return conn.execute(
        "INSERT INTO audit_log (audit_date, audit_type, fills_at_alpaca, fills_in_db, missing_in_db, "
        "missing_at_alpaca, [status], not_run_reason, catch_up_fills, audit_fills, price_mismatches, "
        "quantity_mismatches, share_mismatches, alpaca_cash, expected_cash) OUTPUT INSERTED.audit_id "
        "VALUES (?, 'end_of_day', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (AUDIT_DATE, counts, counts, counts, counts, status, not_run_reason, counts, counts, counts, counts,
         share_mismatches, alpaca_cash, expected_cash)).fetchone()[0]

def insert_failure(conn, audit_id, kind="price_mismatch", ticker="AAPL"):
    """Save one audit_failures row as the bot"""
    conn.execute("INSERT INTO audit_failures (audit_id, kind, ticker, alpaca_fill_id, details) "
                 "VALUES (?, ?, ?, 'fill-1', '{}')", (audit_id, kind, ticker))

def open_failures(conn, audit_id) -> int:
    """Return how many open failed runs v_open_audit_failures shows for one run"""
    return conn.execute("SELECT COUNT(*) FROM v_open_audit_failures WHERE audit_id = ?", audit_id).fetchone()[0]

def test_audit_failure_skip_code_sits_right_after_audit_mismatch(bot_conn):
    """Seed audit_failure between audit_mismatch (40) and drawdown_limit (50)"""

    row = bot_conn.execute("SELECT skip_reason_id, [description], [priority] FROM skip_reasons "
                           "WHERE code = 'audit_failure'").fetchone()

    assert tuple(row) == (24, "An audit found this ticker's records wrong", 45)

def test_pass_row_with_every_count_is_saved(bot_conn):
    """Save a passing run with its counts and cash snapshot"""

    audit_id = insert_audit(bot_conn, alpaca_cash=900, expected_cash=900)

    row = bot_conn.execute("SELECT [status], audit_fills, alpaca_cash FROM audit_log WHERE audit_id = ?",
                           audit_id).fetchone()
    assert (row.status, row.audit_fills, float(row.alpaca_cash)) == ("pass", 0, 900)

def test_not_run_row_with_a_reason_and_no_counts_is_saved(bot_conn):
    """Save a run that couldn't happen: a reason and no counts, shares or cash"""

    audit_id = insert_audit(bot_conn, status="not_run", not_run_reason="Alpaca didn't answer", counts=None,
                            share_mismatches=None)

    assert bot_conn.execute("SELECT [status] FROM audit_log WHERE audit_id = ?", audit_id).fetchone()[0] == "not_run"

@pytest.mark.parametrize("fields", [
    {"status": "not_run", "not_run_reason": None, "counts": None, "share_mismatches": None},
    {"status": "not_run", "not_run_reason": "down", "counts": 0, "share_mismatches": None},
    {"status": "pass", "not_run_reason": "down"},
    {"status": "fail", "counts": None},
])
def test_not_run_and_counts_rule_refuses_a_mixed_row(bot_conn, fields):
    """Refuse not_run without a reason or with counts, and a pass / fail with a reason or without counts"""

    with pytest.raises(pyodbc.IntegrityError, match="ck_audit_log_not_run"):
        insert_audit(bot_conn, **fields)

def test_unknown_status_is_refused(bot_conn):
    """Refuse a status other than pass, fail and not_run"""
    with pytest.raises(pyodbc.IntegrityError, match="ck_audit_log_status"):
        insert_audit(bot_conn, status="skipped")

@pytest.mark.parametrize("alpaca_cash, expected_cash", [(900, None), (None, 900)])
def test_cash_snapshot_needs_both_values(bot_conn, alpaca_cash, expected_cash):
    """Refuse Alpaca's cash without the expected cash, or the reverse"""

    with pytest.raises(pyodbc.IntegrityError, match="ck_audit_log_cash"):
        insert_audit(bot_conn, alpaca_cash=alpaca_cash, expected_cash=expected_cash)

def test_share_check_may_be_skipped(bot_conn):
    """Save a past day's run with no share check (A2 checks shares every cycle)"""

    audit_id = insert_audit(bot_conn, share_mismatches=None)

    assert bot_conn.execute("SELECT share_mismatches FROM audit_log WHERE audit_id = ?", audit_id).fetchone()[0] is None

def test_only_a_failed_run_can_be_resolved(bot_conn):
    """Refuse resolved_at on a passing run"""
    audit_id = insert_audit(bot_conn)

    with pytest.raises(pyodbc.IntegrityError, match="ck_audit_log_resolved"):
        bot_conn.execute("UPDATE audit_log SET resolved_at = SYSUTCDATETIME() WHERE audit_id = ?", audit_id)

def test_bot_can_resolve_a_failed_run(bot_conn):
    """Let the bot set resolved_at on a failed run"""
    audit_id = insert_audit(bot_conn, status="fail")

    bot_conn.execute("UPDATE audit_log SET resolved_at = SYSUTCDATETIME() WHERE audit_id = ?", audit_id)

    assert open_failures(bot_conn, audit_id) == 0

def test_not_run_row_is_not_an_open_failure(bot_conn):
    """Keep not_run out of v_open_audit_failures, so it never blocks buys"""
    audit_id = insert_audit(bot_conn, status="not_run", not_run_reason="down", counts=None, share_mismatches=None)

    assert open_failures(bot_conn, audit_id) == 0

def test_failure_rows_are_saved_per_ticker(bot_conn):
    """Save a ticker failure and a cash failure (no ticker) under one run"""
    audit_id = insert_audit(bot_conn, status="fail")

    insert_failure(bot_conn, audit_id)
    insert_failure(bot_conn, audit_id, kind="cash", ticker=None)

    kinds = bot_conn.execute("SELECT kind FROM audit_failures WHERE audit_id = ? ORDER BY audit_failure_id",
                             audit_id).fetchall()
    assert [row.kind for row in kinds] == ["price_mismatch", "cash"]

@pytest.mark.parametrize("kind, ticker", [("cash", "AAPL"), ("unreadable_activity", "AAPL"),
                                          ("untracked_symbol", "AAPL"), ("price_mismatch", None)])
def test_cash_failures_have_no_ticker_and_others_need_one(bot_conn, kind, ticker):
    """Refuse a ticker on cash and unreadable failures, and a missing ticker on the rest"""
    audit_id = insert_audit(bot_conn, status="fail")

    with pytest.raises(pyodbc.IntegrityError, match="ck_audit_failures_ticker"):
        insert_failure(bot_conn, audit_id, kind=kind, ticker=ticker)

@pytest.mark.parametrize("kind", ["unreadable_activity", "untracked_symbol"])
def test_failures_without_a_ticker_column_value_are_saved(bot_conn, kind):
    """Save an activity nobody could read, or a fill whose symbol doesn't fit the ticker column (an option), as a
    failure with no ticker, like cash"""
    audit_id = insert_audit(bot_conn, status="fail")

    insert_failure(bot_conn, audit_id, kind=kind, ticker=None)

    assert bot_conn.execute("SELECT kind FROM audit_failures WHERE audit_id = ?", audit_id).fetchone()[0] == kind

def test_unknown_failure_kind_is_refused(bot_conn):
    """Refuse a failure kind that isn't on the list"""
    audit_id = insert_audit(bot_conn, status="fail")

    with pytest.raises(pyodbc.IntegrityError, match="ck_audit_failures_kind"):
        insert_failure(bot_conn, audit_id, kind="typo")

def test_failure_needs_an_existing_run(bot_conn):
    """Refuse a failure that points at no run"""
    with pytest.raises(pyodbc.IntegrityError, match="fk_audit_failures_audit_id"):
        insert_failure(bot_conn, 999999)

@pytest.mark.parametrize("statement", ["UPDATE audit_failures SET kind = kind", "DELETE FROM audit_failures"])
def test_bot_cannot_change_or_delete_failures(bot_conn, statement):
    """Keep audit_failures append-only for the bot"""
    insert_failure(bot_conn, insert_audit(bot_conn, status="fail"))

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute(statement)

def test_admin_adjustment_is_read_by_the_bot(bot_conn):
    """Let the admin add a cash adjustment and the bot read it"""

    as_admin(bot_conn, "INSERT INTO cash_adjustments (amount, effective_date, reason, note) "
                       "VALUES (-1.25, '2026-11-24', 'fee', 'monthly data fee')")

    row = bot_conn.execute("SELECT amount, reason FROM cash_adjustments").fetchone()
    assert (float(row.amount), row.reason) == (-1.25, "fee")

@pytest.mark.parametrize("statement", [
    "INSERT INTO cash_adjustments (amount, effective_date, reason) VALUES (5, '2026-11-24', 'deposit')",
    "UPDATE cash_adjustments SET note = note",
    "DELETE FROM cash_adjustments",
])
def test_bot_cannot_write_adjustments(bot_conn, statement):
    """Keep cash_adjustments admin-only"""

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute(statement)

@pytest.mark.parametrize("column, value, constraint", [
    ("amount", 0, "ck_cash_adjustments_amount"),
    ("reason", "gift", "ck_cash_adjustments_reason"),
])
def test_invalid_adjustment_is_refused(bot_conn, column, value, constraint):
    """Refuse a zero amount and an unknown reason"""
    values = {"amount": 5, "reason": "deposit", column: value}

    with pytest.raises(pyodbc.IntegrityError, match=constraint):
        as_admin(bot_conn, "INSERT INTO cash_adjustments (amount, effective_date, reason) VALUES (?, '2026-11-24', ?)",
                 (values["amount"], values["reason"]))

def test_money_columns_use_agreed_types(bot_conn):
    """Store cash like every other money column (19, 4)"""

    rows = bot_conn.execute("SELECT TABLE_NAME, COLUMN_NAME, NUMERIC_PRECISION, NUMERIC_SCALE "
                            "FROM INFORMATION_SCHEMA.COLUMNS WHERE DATA_TYPE = 'decimal' "
                            "AND TABLE_NAME IN ('audit_log', 'cash_adjustments')").fetchall()

    assert {(row.TABLE_NAME, row.COLUMN_NAME): (row.NUMERIC_PRECISION, row.NUMERIC_SCALE) for row in rows} == {
        ("audit_log", "alpaca_cash"): (19, 4),
        ("audit_log", "expected_cash"): (19, 4),
        ("cash_adjustments", "amount"): (19, 4),
    }

@pytest.mark.parametrize("statement", ["UPDATE audit_log SET [status] = 'pass'", "UPDATE audit_log SET notes = 'x'",
                                       "UPDATE audit_log SET alpaca_cash = 1"])
def test_bot_can_change_only_resolved_at(bot_conn, statement):
    """Let the bot set resolved_at and nothing else on a saved run, so a bug can't rewrite a result"""
    insert_audit(bot_conn, status="fail")

    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute(statement)
