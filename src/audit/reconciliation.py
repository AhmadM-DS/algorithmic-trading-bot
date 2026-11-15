"""
reconciliation.py
Once per cycle: record share mismatches that last, repeat their alerts and resolve them when the counts match
"""

#Standard Library
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

#Third Party Libraries
import pyodbc

#Local Imports
from audit.shares import ShareCounts, database_shares
from audit.watch import ReconciliationWatch
from config.constants import RECONCILIATION_FAILED_CHECKS, RECONCILIATION_REPEAT_MINUTES, RECONCILIATION_WAIT_SECONDS
from logger import audit_log
from notifications import send_critical
from storage.reconciliation import MISMATCH, RESOLVED, get_open_mismatches, insert_reconciliation_event

@dataclass(frozen=True)
class ReconciliationReport:
    """What one check did

    status: "done", or "failed" (nothing read or saved; the block in the risk snapshot still holds). blocked is
    every ticker whose buys are blocked this cycle; recorded, repeated and resolved are the tickers that got a new
    mismatch row, a repeated alert or a resolved row.
    """
    status: str
    blocked: tuple = ()
    recorded: tuple = ()
    repeated: tuple = ()
    resolved: tuple = ()

def _naive_utc(moment: datetime) -> datetime:
    """Return a timezone-aware time as naive UTC, as the database stores it"""
    return moment.astimezone(timezone.utc).replace(tzinfo=None)

def _counts_text(ticker: str, counts: ShareCounts) -> str:
    """Return e.g. "ABC: Alpaca 70, database 100", noting a short"""
    text = f"{ticker}: Alpaca {counts.alpaca}, database {counts.database}"
    return text + " (Alpaca shows a short)" if counts.short else text

def _mismatch_message(ticker: str, counts: ShareCounts, since: datetime, now: datetime) -> str:
    """Return the critical alert for a mismatch that lasted the full wait"""
    minutes = int((now - since).total_seconds() // 60)
    return (f"Share mismatch on {_counts_text(ticker, counts)}, for {minutes} minutes. New buys of {ticker} are "
            f"blocked until they match; sells still go out. Check the account and the fill stream.")

def _repeat_message(ticker: str, counts: ShareCounts, recorded_at: datetime) -> str:
    """Return the hourly reminder for a recorded mismatch"""
    return (f"Still a share mismatch on {_counts_text(ticker, counts)} (recorded {recorded_at:%Y-%m-%d %H:%M} UTC). "
            f"Buys of {ticker} stay blocked.")

def _resolved_message(ticker: str, counts: ShareCounts) -> str:
    """Return the alert for a recorded mismatch whose counts match again"""
    return (f"Share mismatch on {ticker} resolved: Alpaca and the database both hold {counts.database}. "
            f"Buys of {ticker} are allowed again.")

def reconcile(conn, context, watch: ReconciliationWatch, alert=send_critical) -> ReconciliationReport:
    """Record, repeat and resolve share mismatches from this cycle's risk snapshot

    The snapshot already blocks a mismatched ticker's buys. This saves a reconciliation_mismatch row and sends a
    critical alert once a mismatch has lasted RECONCILIATION_WAIT_SECONDS, repeats the alert every
    RECONCILIATION_REPEAT_MINUTES, and saves a reconciliation_resolved row with one alert when the counts match.
    A mismatch that clears before the wait (a fill the database saved late) leaves nothing behind. Commits once,
    then sends the alerts. A database error counts as a failed check.

    Parameters:
        conn (Connection): An open database connection; this function commits
        context (RiskContext): This cycle's snapshot from build_context; its as_of is the time now
        watch (ReconciliationWatch): What earlier checks remembered
        alert (callable): Sends a critical alert; Discord by default

    Returns:
        The ReconciliationReport
    """
    now = _naive_utc(context.as_of)
    mismatches = context.share_mismatches
    try:
        recorded = get_open_mismatches(conn)
    except pyodbc.Error as error:
        reconcile_failed(watch, error, alert)
        return ReconciliationReport("failed", blocked=tuple(mismatches))

    for ticker in list(watch.first_seen):
        if ticker not in mismatches and ticker not in recorded:
            audit_log.info(f"{ticker}: share counts match again before the mismatch was recorded")
            watch.forget(ticker)

    new, repeated, resolved = [], [], []
    for ticker, counts in mismatches.items():
        if ticker not in watch.first_seen and ticker not in recorded:
            audit_log.info(f"{_counts_text(ticker, counts)}; buys of {ticker} blocked while it settles")
        since = watch.seen(ticker, now)
        if ticker in recorded:
            if watch.repeat_due(ticker, recorded[ticker]["occurred_at"], now, RECONCILIATION_REPEAT_MINUTES):
                repeated.append((ticker, counts, recorded[ticker]["occurred_at"]))
        elif now - since >= timedelta(seconds=RECONCILIATION_WAIT_SECONDS):
            new.append((ticker, counts, since))
    held = database_shares(context.open_positions)
    for ticker in recorded:
        if ticker not in mismatches:
            resolved.append((ticker, ShareCounts(alpaca=context.broker_shares(ticker), database=held.get(ticker, 0))))

    try:
        for ticker, counts, _ in new:
            insert_reconciliation_event(conn, MISMATCH, ticker, counts.alpaca, counts.database)
        for ticker, counts in resolved:
            insert_reconciliation_event(conn, RESOLVED, ticker, counts.alpaca, counts.database)
        if new or resolved:
            conn.commit()
    except pyodbc.Error as error:
        _rollback(conn)
        reconcile_failed(watch, error, alert)
        return ReconciliationReport("failed", blocked=tuple(mismatches))

    if watch.check_ran():
        _send(alert, audit_log.info, "Share reconciliation is running again.")
    for ticker, counts, since in new:
        _send(alert, audit_log.warning, _mismatch_message(ticker, counts, since, now))
        watch.alerted(ticker, now)
    for ticker, counts, recorded_at in repeated:
        _send(alert, audit_log.warning, _repeat_message(ticker, counts, recorded_at))
        watch.alerted(ticker, now)
    for ticker, counts in resolved:
        _send(alert, audit_log.info, _resolved_message(ticker, counts))
        watch.forget(ticker)
    audit_log.debug(f"Reconciliation: {len(mismatches)} mismatched, {len(new)} recorded, {len(resolved)} resolved")
    return ReconciliationReport("done", blocked=tuple(mismatches), recorded=tuple(t for t, _, _ in new),
                                repeated=tuple(t for t, _, _ in repeated), resolved=tuple(t for t, _ in resolved))

def reconcile_failed(watch: ReconciliationWatch, error: Exception, alert=send_critical) -> bool:
    """Count a check that couldn't run (no risk snapshot, or the database failed); alert once at the limit

    Parameters:
        watch (ReconciliationWatch): What earlier checks remembered
        error (Exception): Why it couldn't run
        alert (callable): Sends a critical alert; Discord by default

    Returns:
        True if this failure sent the alert
    """
    audit_log.warning(f"Share reconciliation couldn't run: {error}")
    if not watch.check_failed(RECONCILIATION_FAILED_CHECKS):
        return False
    alert(f"Share reconciliation couldn't run {watch.failed_checks} times in a row ({error}). Sells still go out; "
          "check Alpaca and the database.")
    return True

def _send(alert, log, message: str):
    """Log a message and send it as a critical alert"""
    log(message)
    alert(message)

def _rollback(conn):
    """Undo this check's unsaved rows, ignoring a connection that's already gone"""
    try:
        conn.rollback()
    except pyodbc.Error as error:
        audit_log.warning(f"Rollback after a failed reconciliation write failed too: {error}")
