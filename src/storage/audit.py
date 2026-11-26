"""
audit.py
Read and write what the end-of-day audit needs: account_activities, audit_log, audit_failures and the trades,
orders and cash it compares
"""

#Standard Library
import json
from datetime import datetime
from decimal import Decimal

#Local Imports
from logger import db_log
from storage.fills import FILL_EVENT_TYPES, FILL_PLACEHOLDERS

COUNT_COLUMNS = ("fills_at_alpaca", "fills_in_db", "missing_in_db", "missing_at_alpaca", "catch_up_fills",
                 "audit_fills", "price_mismatches", "quantity_mismatches", "share_mismatches")

def insert_activity(conn, record: dict) -> bool:
    """Save one account activity unless it's already saved

    The catch-up and the late-activity lookback pull the same days again, so a repeat is normal and skipped quietly.
    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        record (dict): One row from audit.matching.activity_record

    Returns:
        True if it was new and saved, False if it was already there
    """
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO account_activities (alpaca_activity_id, alpaca_order_id, activity_type, activity_at, ticker, "
        "side, quantity, price, net_amount, raw_json) "
        "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ? "
        "WHERE NOT EXISTS (SELECT 1 FROM account_activities WHERE alpaca_activity_id = ?)",
        (record["alpaca_activity_id"], record["alpaca_order_id"], record["activity_type"], record["activity_at"],
         record["ticker"], record["side"], record["quantity"], record["price"], record["net_amount"],
         record["raw_json"], record["alpaca_activity_id"]),
    )
    return cursor.rowcount == 1

def get_trades_between(conn, start: datetime, end: datetime) -> list:
    """Return the current version of every fill between two times, with its ticker, oldest first

    Parameters:
        conn (Connection): An open database connection
        start (datetime): Naive UTC, included
        end (datetime): Naive UTC, not included

    Returns:
        A list of {"alpaca_fill_id", "ticker", "side", "quantity", "fill_price"}
    """
    rows = conn.cursor().execute(
        "SELECT t.alpaca_fill_id, tk.ticker, t.side, t.quantity, t.fill_price "
        "FROM v_trades_current t "
        "JOIN orders o ON o.order_id = t.order_id "
        "JOIN tickers tk ON tk.ticker_id = o.ticker_id "
        "WHERE t.filled_at >= ? AND t.filled_at < ? "
        "ORDER BY t.filled_at, t.trade_id",
        (start, end),
    ).fetchall()
    return [{"alpaca_fill_id": row.alpaca_fill_id, "ticker": row.ticker, "side": row.side,
             "quantity": row.quantity, "fill_price": row.fill_price} for row in rows]

def count_catch_up_fills(conn, start: datetime, end: datetime) -> int:
    """Count the fills the stream missed and the fill stream's catch-up saved, between two times

    Parameters:
        conn (Connection): An open database connection
        start (datetime): Naive UTC, included
        end (datetime): Naive UTC, not included

    Returns:
        The number of catch_up_fill events
    """
    return conn.cursor().execute(
        "SELECT COUNT(DISTINCT execution_id) FROM broker_events "
        "WHERE event_type = 'catch_up_fill' AND event_at >= ? AND event_at < ?",
        (start, end),
    ).fetchone()[0]

def count_audit_fills(conn, start: datetime, end: datetime) -> int:
    """Count the fills audits recorded (saved as "audit_fill" and now in trades) that happened between two times

    Counted from what was saved, so a run after a failed save still reports the fills an earlier run recorded.

    Parameters:
        conn (Connection): An open database connection
        start (datetime): Naive UTC, included
        end (datetime): Naive UTC, not included

    Returns:
        The number of fills
    """
    return conn.cursor().execute(
        "SELECT COUNT(DISTINCT e.execution_id) FROM broker_events e "
        "WHERE e.event_type = 'audit_fill' AND e.event_at >= ? AND e.event_at < ? "
        "AND EXISTS (SELECT 1 FROM trades t WHERE t.alpaca_fill_id = e.execution_id)",
        (start, end),
    ).fetchone()[0]

def get_order_fill_mismatches(conn, start: datetime, end: datetime) -> list:
    """Return orders sent or filled between two times whose filled quantity isn't the sum of their trades

    Parameters:
        conn (Connection): An open database connection
        start (datetime): Naive UTC, included
        end (datetime): Naive UTC, not included

    Returns:
        A list of {"order_id", "client_order_id", "ticker", "filled_quantity", "quantity_in_trades"}
    """
    rows = conn.cursor().execute(
        "SELECT m.order_id, m.client_order_id, tk.ticker, m.filled_quantity, m.quantity_in_trades "
        "FROM v_order_fill_mismatches m "
        "JOIN orders o ON o.order_id = m.order_id "
        "JOIN tickers tk ON tk.ticker_id = o.ticker_id "
        "WHERE (o.submitted_at >= ? AND o.submitted_at < ?) "
        "   OR EXISTS (SELECT 1 FROM trades t WHERE t.order_id = o.order_id AND t.filled_at >= ? AND t.filled_at < ?) "
        "ORDER BY m.order_id",
        (start, end, start, end),
    ).fetchall()
    return [{"order_id": row.order_id, "client_order_id": row.client_order_id, "ticker": row.ticker,
             "filled_quantity": row.filled_quantity, "quantity_in_trades": row.quantity_in_trades} for row in rows]

def get_database_shares(conn) -> dict:
    """Return the shares the database says the bot holds per ticker, over every open position

    Parameters:
        conn (Connection): An open database connection

    Returns:
        {ticker: shares}; tickers with no shares held are left out
    """
    rows = conn.cursor().execute(
        "SELECT ticker, SUM(shares_held) AS shares FROM v_open_positions GROUP BY ticker HAVING SUM(shares_held) <> 0"
    ).fetchall()
    return {row.ticker: row.shares for row in rows}

def get_cash_baseline(conn) -> dict | None:
    """Return the newest audit run whose cash check passed: the starting point of the cash check

    Starting from the newest passing run, not the first, keeps small rounding differences from adding up.

    Parameters:
        conn (Connection): An open database connection

    Returns:
        {"audit_id", "audit_date", "run_at" (naive UTC), "alpaca_cash"}, or None if no run's cash check passed yet
    """
    row = conn.cursor().execute(
        "SELECT TOP 1 a.audit_id, a.audit_date, a.run_at, a.alpaca_cash FROM audit_log a "
        "WHERE a.alpaca_cash IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM audit_failures f WHERE f.audit_id = a.audit_id AND f.kind = 'cash') "
        "ORDER BY a.run_at DESC, a.audit_id DESC"
    ).fetchone()
    if row is None:
        return None
    return {"audit_id": row.audit_id, "audit_date": row.audit_date, "run_at": row.run_at,
            "alpaca_cash": row.alpaca_cash}

def get_cash_movements(conn, baseline_audit_id: int) -> dict:
    """Return the cash the database knows moved since the cash check's starting run, in three parts

    trades: every fill after the run (sells add, buys subtract). activities: non-fill activities (fees, deposits,
    dividends) saved after the run, since Alpaca's cash moves when they post, which only a later pull shows.
    adjustments: the cash_adjustments rows the owner entered after the run (one entered before it was already in
    the cash the run read, or the run's cash check wouldn't have passed). Times are compared in SQL, at the
    column's full 100 ns precision: Python's datetime would drop the last digit and count an activity saved in the
    same tick as the run.

    Parameters:
        conn (Connection): An open database connection
        baseline_audit_id (int): The starting run, from get_cash_baseline

    Returns:
        {"trades", "activities", "adjustments"} as Decimal (0 when nothing moved)
    """
    cursor = conn.cursor()
    trades = cursor.execute(
        "SELECT SUM(CASE WHEN t.side = 'sell' THEN t.quantity * t.fill_price ELSE -t.quantity * t.fill_price END) "
        "FROM v_trades_current t JOIN audit_log b ON b.audit_id = ? WHERE t.filled_at > b.run_at",
        (baseline_audit_id,),
    ).fetchone()[0]
    activities = cursor.execute(
        "SELECT SUM(a.net_amount) FROM account_activities a JOIN audit_log b ON b.audit_id = ? "
        "WHERE a.activity_type <> 'FILL' AND a.loaded_at > b.run_at",
        (baseline_audit_id,),
    ).fetchone()[0]
    adjustments = cursor.execute(
        "SELECT SUM(c.amount) FROM cash_adjustments c JOIN audit_log b ON b.audit_id = ? "
        "WHERE c.created_at > b.run_at",
        (baseline_audit_id,),
    ).fetchone()[0]
    return {"trades": trades or Decimal(0), "activities": activities or Decimal(0),
            "adjustments": adjustments or Decimal(0)}

def get_dated_activities(conn, start: datetime, end: datetime) -> list:
    """Return the non-fill activities (fees, deposits, dividends, splits) stamped between two times

    Parameters:
        conn (Connection): An open database connection
        start (datetime): Naive UTC, included
        end (datetime): Naive UTC, not included

    Returns:
        A list of {"activity_type", "net_amount", "activity_at", "ticker"}, oldest first
    """
    rows = conn.cursor().execute(
        "SELECT activity_type, net_amount, activity_at, ticker FROM account_activities "
        "WHERE activity_type <> 'FILL' AND activity_at >= ? AND activity_at < ? "
        "ORDER BY activity_at, account_activity_id",
        (start, end),
    ).fetchall()
    return [{"activity_type": row.activity_type, "net_amount": row.net_amount, "activity_at": row.activity_at,
             "ticker": row.ticker} for row in rows]

def insert_audit(conn, *, audit_date, audit_type: str, counts: dict, status: str, notes: str | None = None,
                 alpaca_cash: Decimal | None = None, expected_cash: Decimal | None = None) -> int:
    """Save one audit run that ran and return its audit_id

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        audit_date (date): The New York day it audited
        audit_type (str): "end_of_day" or "catch_up"
        counts (dict): Every column in COUNT_COLUMNS; share_mismatches None when shares weren't checked
        status (str): "pass" or "fail"
        notes (str | None): A readable summary
        alpaca_cash (Decimal | None): Alpaca's cash, None when cash wasn't checked
        expected_cash (Decimal | None): The cash the database expected, None when cash wasn't checked

    Returns:
        The new audit_id as an int
    """
    columns = ", ".join(COUNT_COLUMNS)
    cursor = conn.cursor()
    cursor.execute(
        f"INSERT INTO audit_log (audit_date, audit_type, [status], notes, alpaca_cash, expected_cash, {columns}) "
        f"OUTPUT INSERTED.audit_id VALUES (?, ?, ?, ?, ?, ?, {', '.join('?' * len(COUNT_COLUMNS))})",
        (audit_date, audit_type, status, notes, alpaca_cash, expected_cash,
         *(counts[column] for column in COUNT_COLUMNS)),
    )
    audit_id = cursor.fetchone()[0]
    db_log.debug(f"audit_log saved: {audit_type} {audit_date} {status} as {audit_id}")
    return audit_id

def insert_failures(conn, audit_id: int, failures: list):
    """Save one audit_failures row per problem a run found, its details as JSON

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        audit_id (int): The run they belong to
        failures (list): audit.matching.Failure items
    """
    cursor = conn.cursor()
    for failure in failures:
        cursor.execute(
            "INSERT INTO audit_failures (audit_id, kind, ticker, alpaca_fill_id, details) VALUES (?, ?, ?, ?, ?)",
            (audit_id, failure.kind, failure.ticker, failure.fill_id, json.dumps(failure.details)),
        )

def insert_not_run(conn, audit_date, audit_type: str, reason: str) -> int:
    """Save a run that couldn't happen, with why, and return its audit_id

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        audit_date (date): The New York day it would have audited
        audit_type (str): "end_of_day" or "catch_up"
        reason (str): Why, cut to 250 characters

    Returns:
        The new audit_id as an int
    """
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO audit_log (audit_date, audit_type, [status], not_run_reason) OUTPUT INSERTED.audit_id "
        "VALUES (?, ?, 'not_run', ?)",
        (audit_date, audit_type, reason[:250]),
    )
    return cursor.fetchone()[0]

def get_latest_audits(conn) -> dict:
    """Return each audited day's newest run

    Parameters:
        conn (Connection): An open database connection

    Returns:
        {audit_date: {"audit_id", "status", "resolved_at"}}
    """
    rows = conn.cursor().execute(
        "SELECT audit_date, audit_id, [status], resolved_at FROM ("
        "    SELECT audit_date, audit_id, [status], resolved_at, "
        "           ROW_NUMBER() OVER (PARTITION BY audit_date ORDER BY run_at DESC, audit_id DESC) AS newest "
        "    FROM audit_log"
        ") ranked WHERE newest = 1"
    ).fetchall()
    return {row.audit_date: {"audit_id": row.audit_id, "status": row.status, "resolved_at": row.resolved_at}
            for row in rows}

def _keys_by_audit(conn, audit_ids: list) -> dict:
    """Return {audit_id: set of (kind, ticker, alpaca_fill_id)} for some runs"""
    if not audit_ids:
        return {}
    placeholders = ", ".join("?" * len(audit_ids))
    rows = conn.cursor().execute(
        "SELECT DISTINCT audit_id, kind, ticker, alpaca_fill_id FROM audit_failures "
        f"WHERE audit_id IN ({placeholders})",
        tuple(audit_ids),
    ).fetchall()
    keys = {audit_id: set() for audit_id in audit_ids}
    for row in rows:
        keys[row.audit_id].add((row.kind, row.ticker, row.alpaca_fill_id))
    return keys

def get_open_audits(conn) -> list:
    """Return every failed run not resolved yet, oldest first, with the problems it found

    Parameters:
        conn (Connection): An open database connection

    Returns:
        A list of {"audit_id", "audit_date", "run_at", "kinds", "keys"}: kinds is a set of failure kinds, keys a set
        of (kind, ticker, alpaca_fill_id)
    """
    rows = conn.cursor().execute(
        "SELECT audit_id, audit_date, run_at FROM v_open_audit_failures ORDER BY run_at, audit_id"
    ).fetchall()
    keys = _keys_by_audit(conn, [row.audit_id for row in rows])
    return [{"audit_id": row.audit_id, "audit_date": row.audit_date, "run_at": row.run_at,
             "kinds": {key[0] for key in keys[row.audit_id]}, "keys": keys[row.audit_id]} for row in rows]

def get_runs_after(conn, audit_id: int) -> list:
    """Return every run saved after one run, oldest first, with what each checked and the kinds it found

    Parameters:
        conn (Connection): An open database connection
        audit_id (int): Runs with a higher audit_id are returned

    Returns:
        A list of {"audit_id", "audit_date", "status", "share_mismatches", "alpaca_cash", "kinds"}
    """
    rows = conn.cursor().execute(
        "SELECT audit_id, audit_date, [status], share_mismatches, alpaca_cash FROM audit_log "
        "WHERE audit_id > ? ORDER BY audit_id",
        (audit_id,),
    ).fetchall()
    keys = _keys_by_audit(conn, [row.audit_id for row in rows])
    return [{"audit_id": row.audit_id, "audit_date": row.audit_date, "status": row.status,
             "share_mismatches": row.share_mismatches, "alpaca_cash": row.alpaca_cash,
             "kinds": {key[0] for key in keys[row.audit_id]}} for row in rows]

def resolve_audits(conn, audit_ids: list) -> int:
    """Mark failed runs as resolved now

    Doesn't commit.

    Parameters:
        conn (Connection): An open database connection
        audit_ids (list): The runs to resolve

    Returns:
        How many runs were resolved
    """
    if not audit_ids:
        return 0
    placeholders = ", ".join("?" * len(audit_ids))
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE audit_log SET resolved_at = SYSUTCDATETIME() "
        f"WHERE audit_id IN ({placeholders}) AND [status] = 'fail' AND resolved_at IS NULL",
        tuple(audit_ids),
    )
    return cursor.rowcount

def get_open_failure_tickers(conn, exclude_kinds: tuple = ()) -> frozenset:
    """Return every ticker with a failure on a run not resolved yet

    Parameters:
        conn (Connection): An open database connection
        exclude_kinds (tuple): Failure kinds to leave out, e.g. ones that don't block buys

    Returns:
        A frozenset of tickers
    """
    placeholders = ", ".join("?" * len(exclude_kinds))
    left_out = f" AND f.kind NOT IN ({placeholders})" if exclude_kinds else ""
    rows = conn.cursor().execute(
        "SELECT DISTINCT f.ticker FROM audit_failures f "
        "JOIN v_open_audit_failures o ON o.audit_id = f.audit_id "
        f"WHERE f.ticker IS NOT NULL{left_out}",
        tuple(exclude_kinds),
    ).fetchall()
    return frozenset(row.ticker for row in rows)

def get_first_activity_time(conn) -> datetime | None:
    """Return the oldest saved fill, order or Alpaca event, where the audit's catch-up starts

    Orders and events (by Alpaca's time, else when saved) count too, so a first day whose fills the stream all
    missed is still audited.

    Parameters:
        conn (Connection): An open database connection

    Returns:
        Naive UTC, or None if none of them is saved yet
    """
    return conn.cursor().execute(
        "SELECT MIN(first_at) FROM ("
        "    SELECT MIN(filled_at) AS first_at FROM trades"
        "    UNION ALL SELECT MIN(submitted_at) FROM orders"
        "    UNION ALL SELECT MIN(COALESCE(event_at, received_at)) FROM broker_events"
        ") firsts"
    ).fetchone()[0]

def get_open_failure_keys(conn, audit_date, any_day_kinds: tuple = ()) -> set:
    """Return the problems already open for one day, plus open problems of some kinds on any day

    Parameters:
        conn (Connection): An open database connection
        audit_date (date): The New York day
        any_day_kinds (tuple): Kinds that belong to the account, not a day (shares, cash): open ones count whatever
            day found them

    Returns:
        A set of (kind, ticker, alpaca_fill_id) tuples; ticker and alpaca_fill_id may be None
    """
    placeholders = ", ".join("?" * len(any_day_kinds))
    any_day = f" OR f.kind IN ({placeholders})" if any_day_kinds else ""
    rows = conn.cursor().execute(
        "SELECT DISTINCT f.kind, f.ticker, f.alpaca_fill_id FROM audit_failures f "
        f"JOIN v_open_audit_failures o ON o.audit_id = f.audit_id WHERE o.audit_date = ?{any_day}",
        (audit_date, *any_day_kinds),
    ).fetchall()
    return {(row.kind, row.ticker, row.alpaca_fill_id) for row in rows}

def get_saved_fill(conn, fill_id: str) -> dict | None:
    """Return the saved fill event for one fill ID whose handling never finished (no trades row), if any

    A message saved unreadable (no Alpaca order ID) is left out.

    Parameters:
        conn (Connection): An open database connection
        fill_id (str): Alpaca's execution ID for the fill

    Returns:
        {"event_type", "raw_json"} of the oldest such event, or None
    """
    row = conn.cursor().execute(
        f"SELECT TOP 1 e.event_type, e.raw_json FROM broker_events e "
        f"WHERE e.execution_id = ? AND e.event_type IN ({FILL_PLACEHOLDERS}) AND e.alpaca_order_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM trades t WHERE t.alpaca_fill_id = e.execution_id) "
        "ORDER BY e.broker_event_id",
        (fill_id, *FILL_EVENT_TYPES),
    ).fetchone()
    return None if row is None else {"event_type": row.event_type, "raw_json": row.raw_json}
