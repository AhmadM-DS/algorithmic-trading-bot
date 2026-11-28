"""
end_of_day.py
The end-of-day audit: match each day's fills, orders, shares and cash to Alpaca's, record what the fill stream
missed, save the result, catch up on missed days and remind while a failure is open
"""

#Standard Library
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

#Third Party Libraries
import pyodbc

#Local Imports
from audit.matching import (DAY_KINDS, NOT_BLOCKING_KINDS, NOW_KINDS, TICKER_LENGTH, UNREADABLE_ERRORS, Failure,
                            Fill, activity_day,
                            activity_record, alpaca_fill, cash_failure, day_window, fits_ticker, is_fill_activity,
                            match_fills)
from audit.shares import compare_shares
from audit.watch import AuditWatch
from config.constants import (ACTIVITY_LOOKBACK_DAYS, AUDIT_CATCH_UP_MAX_DAYS, AUDIT_MINUTES_AFTER_CLOSE,
                              AUDIT_REPEAT_MINUTES, CASH_TOLERANCE)
from data.market_calendar import NEW_YORK, session_times
from execution.broker import BrokerError
from fills.events import from_activity, from_saved
from fills.handler import Alert, HandleResult, process_update
from logger import audit_log
from notifications import send, send_critical
from storage.audit import (count_audit_fills, count_catch_up_fills, get_cash_baseline, get_cash_movements,
                           get_database_shares, get_dated_activities, get_first_activity_time, get_latest_audits,
                           get_open_audits, get_open_failure_keys, get_open_failure_tickers, get_order_fill_mismatches,
                           get_runs_after, get_saved_fill, get_trades_between, insert_activity, insert_audit,
                           insert_failures, insert_not_run, resolve_audits)
from storage.connections import is_connection_error
from storage.events import insert_bot_event
from storage.fills import trade_exists

END_OF_DAY = "end_of_day"
CATCH_UP = "catch_up"
NOT_RUN_EVENT = "audit_not_run"
BATCH_STOPPING_CAUSES = ("alpaca", "database")
DAY_CAUSES = ("data", "unexpected")
NOT_A_RECORD = "not a record"
ALERT_ONCE_KINDS = (*NOW_KINDS, "unreadable_activity")

@dataclass(frozen=True)
class AuditReport:
    """What one audit run did

    status: "pass", "fail", "not_run" (Alpaca didn't answer; saved as such) or "failed" (the database or something
    unexpected failed; the run wasn't saved). audit_fills counts the fills this run recorded. resolved holds the
    audit_ids of earlier failed runs this run resolved. cause says why a run didn't finish: "alpaca", "database"
    (the connection failed), "data" (another database error) or "unexpected".
    """
    audit_date: date
    status: str
    audit_id: int | None = None
    failures: tuple = ()
    audit_fills: int = 0
    resolved: tuple = ()
    cause: str | None = None

def _naive_utc(moment: datetime) -> datetime:
    """Return a timezone-aware time as naive UTC, as the database stores it"""
    return moment.astimezone(timezone.utc).replace(tzinfo=None)

def _new_york_date(moment: datetime) -> date:
    """Return the New York date of a time; a naive time is taken as UTC"""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ZoneInfo(NEW_YORK)).date()

def _lookback_start(audit_date: date, calendar: dict) -> date:
    """Return the trading day ACTIVITY_LOOKBACK_DAYS before the audited day, or the calendar's first day"""
    earlier = sorted(day for day in calendar if day <= audit_date) or [audit_date]
    return earlier[max(0, len(earlier) - 1 - ACTIVITY_LOOKBACK_DAYS)]

def _saved_update(conn, fill_id: str):
    """Return the saved, unhandled event of one fill rebuilt as a TradeUpdate, or None if there's none or it can't
    be read"""
    saved = get_saved_fill(conn, fill_id)
    if saved is None:
        return None
    try:
        return from_saved(saved["event_type"], saved["raw_json"])
    except UNREADABLE_ERRORS as error:
        audit_log.warning(f"Saved event of fill {fill_id} can't be read ({type(error).__name__}: {error}); "
                          "recording it from Alpaca's activity")
        return None

def _repair(conn, fills: list, now: datetime, send, alerted: set) -> list:
    """Record every one of Alpaca's fills that has no trades row, through the fill stream's own code

    A fill saved raw whose handling never finished is handled again from that event; a fill never seen, or whose
    saved event can't be read, is saved as "audit_fill" from Alpaca's activity. Each fill's alerts go out as it's
    handled. A fill that can't be recorded (a database error, or one nobody expected) is rolled back, alerted and
    skipped, so it stays missing_in_db, unless the connection itself failed. A fill an earlier run already failed to
    record (in alerted) is only logged when it fails again, so a re-audit doesn't repeat its alerts.

    Parameters:
        fills (list): (activity, Fill) pairs of the day
        send (callable): Sends a list of (channel, message) alerts
        alerted (set): Fill IDs already open as missing_in_db on this day

    Returns:
        The tickers of the fills recorded now

    Raises:
        pyodbc.Error if the database connection failed
    """
    recorded = []
    for activity, fill in fills:
        if trade_exists(conn, fill.fill_id):
            continue
        try:
            update = _saved_update(conn, fill.fill_id)
            if update is not None:
                result = process_update(conn, update, now, save_raw=False)
            else:
                result = process_update(conn, from_activity(activity, event_type="audit_fill"), now)
        except Exception as error:
            if isinstance(error, pyodbc.Error) and is_connection_error(error):
                raise
            _rollback(conn)
            audit_log.error(f"Audit couldn't record fill {fill.fill_id} ({fill.ticker}): {type(error).__name__}: "
                            f"{error}")
            result = HandleResult("failed", [Alert("critical", f"End-of-day audit couldn't record fill {fill.fill_id} "
                                                          f"({fill.ticker}): {type(error).__name__}: {error}. It stays "
                                                          "a missing_in_db failure until fixed.")])
        if result.outcome == "handled":
            recorded.append(fill.ticker)
            send(result.alerts)
        elif fill.fill_id in alerted:
            audit_log.warning(f"Fill {fill.fill_id} ({fill.ticker}) still can't be recorded ({result.outcome}); "
                              "already alerted")
        else:
            send(result.alerts)
    return recorded

def _unreadable(activity, error: Exception) -> Failure:
    """Return the failure for an activity that can't be read, even one that isn't a dict"""
    activity_id = str(activity.get("id")) if isinstance(activity, dict) else NOT_A_RECORD
    audit_log.warning(f"Activity {activity_id} can't be read: {type(error).__name__}: {error}")
    return Failure("unreadable_activity", None, activity_id[:128],
                   {"error": f"{type(error).__name__}: {error}", "activity": json.dumps(activity, default=str)})

def _untracked(fill: Fill) -> Failure:
    """Return the failure for a fill whose symbol doesn't fit the ticker column (an option)"""
    audit_log.warning(f"Fill {fill.fill_id} of {fill.ticker} can't be recorded: the symbol is longer than "
                      f"{TICKER_LENGTH} characters")
    return Failure("untracked_symbol", None, fill.fill_id, {"symbol": fill.ticker, **fill.as_details()})

def _read_activities(activities: list, audit_date: date) -> tuple:
    """Read every activity

    An unreadable activity belongs to the day its time, date or ID names (activity_day); one with none of those
    belongs to every day audited. A fill whose symbol doesn't fit the ticker column is never recorded.

    Returns:
        (records to save, the day's (activity, Fill) pairs to record and match, the day's failures for activities
        that can't be read or fills that can't be recorded)
    """
    records, fills, failures = [], [], []
    for activity in activities:
        try:
            record = activity_record(activity)
            fill = alpaca_fill(activity) if is_fill_activity(activity) else None
            if fill is not None and fits_ticker(fill.ticker):
                from_activity(activity)
        except UNREADABLE_ERRORS as error:
            if activity_day(activity) in (None, audit_date):
                failures.append(_unreadable(activity, error))
            continue
        records.append(record)
        if fill is None or _new_york_date(record["activity_at"]) != audit_date:
            continue
        if fits_ticker(fill.ticker):
            fills.append((activity, fill))
        else:
            failures.append(_untracked(fill))
    return records, fills, failures

def _database_fills(conn, start: datetime, end: datetime) -> list:
    """Return the day's current trades as Fills"""
    return [Fill(row["alpaca_fill_id"], row["ticker"], row["side"], Decimal(row["quantity"]), row["fill_price"])
            for row in get_trades_between(conn, start, end)]

def _order_failures(conn, start: datetime, end: datetime) -> list:
    """Return one failure per order of the day whose filled quantity isn't the sum of its trades"""
    return [Failure("order_fill_mismatch", row["ticker"], None,
                    {"client_order_id": row["client_order_id"], "filled_quantity": row["filled_quantity"],
                     "quantity_in_trades": row["quantity_in_trades"]})
            for row in get_order_fill_mismatches(conn, start, end)]

def _expected_cash(conn, alpaca_cash: Decimal) -> Decimal:
    """Return the starting cash plus every movement the database knows since; Alpaca's cash on the first check"""
    baseline = get_cash_baseline(conn)
    if baseline is None:
        return alpaca_cash
    movements = get_cash_movements(conn, baseline["audit_id"])
    return baseline["alpaca_cash"] + sum(movements.values())

def _cleared(run: dict, later: list) -> bool:
    """Return True if later runs re-checked every kind of problem a failed run found and found it gone

    A day's fill and order problems clear when that day is audited again cleanly; shares and cash clear on any later
    run that checked them.
    """
    if run["kinds"] & set(DAY_KINDS) and not any(
            other["audit_date"] == run["audit_date"] and other["status"] != "not_run"
            and not other["kinds"] & set(DAY_KINDS) for other in later):
        return False
    if "share_mismatch" in run["kinds"] and not any(other["share_mismatches"] == 0 for other in later):
        return False
    if "cash" in run["kinds"] and not any(other["alpaca_cash"] is not None and "cash" not in other["kinds"]
                                          for other in later):
        return False
    return True

def _rechecked(run: dict, current: dict) -> bool:
    """Return True if the current run checked again every kind of problem an older failed run found

    A day's fill problems are checked again only by a run of that day that read every one of its activities.
    """
    if run["kinds"] & set(DAY_KINDS) and (current["audit_date"] != run["audit_date"] or not current["complete"]):
        return False
    if "share_mismatch" in run["kinds"] and current["share_mismatches"] is None:
        return False
    return not ("cash" in run["kinds"] and current["alpaca_cash"] is None)

def _resolve_cleared(conn, current: dict) -> tuple:
    """Resolve every older open failed run whose problems later runs found gone, or the current run checked again

    An older run the current run checked again is resolved too: the current run carries the problems it still
    found, so each problem has one open run (and one run to resolve by hand).

    Returns:
        (the runs whose problems are all gone, [(replaced run, the keys of its problems now gone)])
    """
    cleared, gone = [], []
    for run in get_open_audits(conn):
        if run["audit_id"] == current["audit_id"]:
            continue
        if _cleared(run, get_runs_after(conn, run["audit_id"])):
            cleared.append(run)
        elif run["audit_id"] in current["carried_from"] or _rechecked(run, current):
            gone.append((run, sorted(run["keys"] - current["keys"], key=str)))
    resolve_audits(conn, [run["audit_id"] for run in cleared] + [run["audit_id"] for run, _ in gone])
    return cleared, [(run, keys) for run, keys in gone if keys]

def _carry_forward(conn, audit_date: date, complete: bool, checked: dict) -> tuple:
    """Return the share and cash failures this run takes over from older open runs of its day, and those runs

    A run of the same day that read every activity checked that day's fill and order problems again. The older
    run's share and cash failures it didn't check move to it, marked with where they came from, so the older run can
    be resolved and a ticker whose fill problem is gone isn't kept blocked by a share or cash problem.

    Parameters:
        checked (dict): {"share_mismatch": bool, "cash": bool}, whether this run checked each

    Returns:
        (Failures to save with this run, the audit_ids of the runs they came from)
    """
    if not complete:
        return [], set()
    carried, sources = {}, set()
    for run in get_open_audits(conn):
        unchecked = {kind for kind in run["kinds"] & set(NOW_KINDS) if not checked[kind]}
        if run["audit_date"] != audit_date or not run["kinds"] & set(DAY_KINDS) or not unchecked:
            continue
        for kind, ticker, fill_id in sorted(run["keys"], key=str):
            if kind in unchecked:
                carried.setdefault((kind, ticker, fill_id),
                                   Failure(kind, ticker, fill_id, {"carried_from": run["audit_id"]}))
        sources.add(run["audit_id"])
    return list(carried.values()), sources

def _key_line(key: tuple) -> str:
    """Return one readable line for a (kind, ticker, alpaca_fill_id) problem key"""
    kind, ticker, fill_id = key
    return kind + (f" on {ticker}" if ticker else "") + (f" fill {fill_id}" if fill_id else "")

def _failure_line(failure: Failure) -> str:
    """Return one readable line for a failure"""
    if failure.kind == "cash":
        details = failure.details
        moved = ", ".join(f"{item['type']} {item['net_amount']}" for item in details["activities"]) or "none"
        return (f"cash: Alpaca {details['alpaca_cash']}, expected {details['expected_cash']} (difference "
                f"{details['difference']}); other activities that day: {moved}")
    if failure.kind == "unreadable_activity":
        return f"unreadable activity {failure.fill_id} ({failure.details['error']})"
    if failure.kind == "untracked_symbol":
        return (f"fill {failure.fill_id} of {failure.details['symbol']} can't be recorded (the symbol is longer than "
                f"{TICKER_LENGTH} characters, e.g. an option); check it by hand")
    fill = f" fill {failure.fill_id}" if failure.fill_id else ""
    return f"{failure.kind} on {failure.ticker}{fill}"

def _failure_message(audit_date: date, failures: list) -> str:
    """Return the critical alert for a failed run's new problems"""
    blocked = sorted({f.ticker for f in failures if f.kind not in NOT_BLOCKING_KINDS and f.ticker})
    block = (f" Buys of {', '.join(blocked)} are blocked until it's resolved; sells still go out."
             if blocked else " No buys are blocked.")
    return f"End-of-day audit of {audit_date} failed: " + "; ".join(_failure_line(f) for f in failures) + "." + block

def _send_all(alerts: list, alert, notify):
    """Send the fill handler's alerts: critical through alert, the rest through notify with their kind and asset"""
    for kind, message, asset in alerts:
        if kind == "critical":
            alert(message)
        else:
            notify(kind, message, asset)

def _rollback(conn):
    """Undo the run's unsaved rows, ignoring a connection that's already gone"""
    try:
        conn.rollback()
    except pyodbc.Error as error:
        audit_log.warning(f"Rollback after a failed audit write failed too: {error}")

def _not_run(conn, audit_date: date, audit_type: str, reason: str, watch: AuditWatch, alert) -> AuditReport:
    """Save a run Alpaca didn't answer for, with a bot_events row, and alert once per outage"""
    audit_log.warning(f"Audit of {audit_date} couldn't run: {reason}")
    try:
        audit_id = insert_not_run(conn, audit_date, audit_type, reason)
        insert_bot_event(conn, NOT_RUN_EVENT, json.dumps({"audit_date": str(audit_date), "audit_id": audit_id}))
        conn.commit()
    except pyodbc.Error as error:
        _rollback(conn)
        audit_log.error(f"Couldn't save the not_run run of {audit_date}: {type(error).__name__}: {error}")
        audit_id = None
        reason = f"{reason}; the not_run row couldn't be saved either ({error})"
    if watch.outage("alpaca"):
        alert(f"End-of-day audit of {audit_date} couldn't run: {reason}. The next catch-up audits the day again.")
    return AuditReport(audit_date, "not_run", audit_id, cause="alpaca")

def _database_failed(conn, audit_date: date, error: Exception, watch: AuditWatch, alert) -> AuditReport:
    """Undo the run and alert once per cause; the day has no row, so the next catch-up audits it"""
    _rollback(conn)
    audit_log.error(f"Audit of {audit_date} failed on the database: {type(error).__name__}: {error}")
    cause = "database" if is_connection_error(error) else "data"
    if watch.outage(cause):
        alert(f"End-of-day audit of {audit_date} couldn't save: database error ({type(error).__name__}: {error}). "
              "The next catch-up audits the day again.")
    return AuditReport(audit_date, "failed", cause=cause)

def run_audit(conn, broker, audit_date: date, now: datetime, calendar: dict, *, check_now: bool = True,
              watch: AuditWatch | None = None, alert=send_critical, notify=send) -> AuditReport:
    """Audit one New York trading day against Alpaca and save the result

    Order: read Alpaca (activities to the day's end, or up to now with check_now, then the cash and positions); save
    every activity raw and commit;
    record fills the stream missed through the fill stream's code; match the day's fills and orders; with check_now
    compare shares and cash as they are now; save the run and its failures, resolve earlier failures it shows gone,
    commit; then alert. Alpaca not answering saves a not_run run; a database error saves nothing. Never raises.

    Parameters:
        conn (Connection): An open database connection; this function commits
        broker (AlpacaBroker): Asked for activities, and with check_now the account and positions
        audit_date (date): The New York day to audit
        now (datetime): The time now, timezone-aware
        calendar (dict): Trading days from get_calendar, reaching ACTIVITY_LOOKBACK_DAYS before audit_date
        check_now (bool): Also compare shares and cash as they are now; only right while the market is closed
        watch (AuditWatch | None): What earlier runs remembered; None alerts every outage
        alert (callable): Sends a critical alert; Discord by default
        notify (callable): Sends (kind, message, asset) like notifications.send, e.g. a manual trade note

    Returns:
        An AuditReport
    """
    watch = watch or AuditWatch()
    moment = _naive_utc(now)
    audit_type = END_OF_DAY if audit_date == _new_york_date(now) else CATCH_UP
    start, end = day_window(audit_date)
    until = max(end, moment) if check_now else end
    try:
        activities = broker.get_activities(day_window(_lookback_start(audit_date, calendar))[0], until)
        account = broker.get_account() if check_now else None
        held = broker.get_positions() if check_now else None
    except BrokerError as error:
        return _not_run(conn, audit_date, audit_type, f"Alpaca didn't answer: {error}", watch, alert)
    except Exception as error:
        return _not_run(conn, audit_date, audit_type,
                        f"Alpaca's answer couldn't be read: {type(error).__name__}: {error}", watch, alert)

    saved = False
    try:
        records, day_fills, activity_failures = _read_activities(activities, audit_date)
        for record in records:
            insert_activity(conn, record)
        conn.commit()
        saved = True
        known = get_open_failure_keys(conn, audit_date, any_day_kinds=ALERT_ONCE_KINDS)
        alerted = {fill_id for kind, _, fill_id in known if kind == "missing_in_db"}
        recorded = _repair(conn, day_fills, moment, lambda alerts: _send_all(alerts, alert, notify), alerted)
        if recorded:
            alert(f"End-of-day audit of {audit_date} recorded {len(recorded)} fill(s) the fill stream missed "
                  f"({', '.join(sorted(set(recorded)))}). Check that the fill stream is running.")

        database = _database_fills(conn, start, end)
        match = match_fills([fill for _, fill in day_fills], database)
        failures = activity_failures + match.failures() + _order_failures(conn, start, end)
        share_count = alpaca_cash = expected_cash = None
        cash_note = ""
        if check_now:
            untracked = sorted(symbol for symbol in held if not fits_ticker(symbol))
            if untracked:
                audit_log.warning(f"Audit of {audit_date}: positions left out of the share check (symbols too long "
                                  f"to record): {', '.join(untracked)}")
                cash_note = f"; positions not share-checked: {', '.join(untracked)}"
            held = {symbol: shares for symbol, shares in held.items() if fits_ticker(symbol)}
            shares = compare_shares(held, get_database_shares(conn))
            failures += [Failure("share_mismatch", ticker, None, {"alpaca": counts.alpaca, "database": counts.database})
                         for ticker, counts in shares.items()]
            share_count = len(shares)
            if account.cash is None:
                audit_log.warning(f"Audit of {audit_date}: Alpaca sent no cash, so the cash check was skipped")
                cash_note += "; cash not checked (Alpaca sent no cash)"
            else:
                alpaca_cash = account.cash
                expected_cash = _expected_cash(conn, alpaca_cash)
                cash = cash_failure(alpaca_cash, expected_cash, CASH_TOLERANCE, get_dated_activities(conn, start, end))
                failures += [cash] if cash else []

        audit_fills = count_audit_fills(conn, start, end)
        counts = {"fills_at_alpaca": len(day_fills), "fills_in_db": len(database),
                  "missing_in_db": audit_fills + len(match.missing_in_db),
                  "missing_at_alpaca": len(match.missing_at_alpaca),
                  "catch_up_fills": count_catch_up_fills(conn, start, end), "audit_fills": audit_fills,
                  "price_mismatches": len(match.price_mismatches),
                  "quantity_mismatches": len(match.quantity_mismatches), "share_mismatches": share_count}
        complete = not any(failure.kind == "unreadable_activity" for failure in failures)
        carried, carried_from = _carry_forward(conn, audit_date, complete,
                                               {"share_mismatch": share_count is not None,
                                                "cash": alpaca_cash is not None})
        found = failures
        failures = failures + carried
        status = "fail" if failures else "pass"
        notes = (f"{len(day_fills)} fills at Alpaca, {len(database)} in the database, {audit_fills} recorded by "
                 f"audits, {len(found)} problems{cash_note}"
                 + (f"; {len(carried)} unchecked share or cash problems carried from earlier runs" if carried else ""))
        audit_id = insert_audit(conn, audit_date=audit_date, audit_type=audit_type, counts=counts, status=status,
                                notes=notes, alpaca_cash=alpaca_cash, expected_cash=expected_cash)
        insert_failures(conn, audit_id, failures)
        resolved, gone = _resolve_cleared(conn, {
            "audit_id": audit_id, "audit_date": audit_date, "share_mismatches": share_count,
            "alpaca_cash": alpaca_cash, "complete": complete, "carried_from": carried_from,
            "keys": {(failure.kind, failure.ticker, failure.fill_id) for failure in failures}})
        conn.commit()
    except pyodbc.Error as error:
        return _database_failed(conn, audit_date, error, watch, alert)
    except Exception as error:
        _rollback(conn)
        audit_log.error(f"Audit of {audit_date} failed: {type(error).__name__}: {error}")
        if watch.outage("unexpected"):
            kept = ("The activities and any fills it recorded were saved; the audit result wasn't." if saved
                    else "Nothing was saved.")
            alert(f"End-of-day audit of {audit_date} failed unexpectedly ({type(error).__name__}: {error}). {kept} "
                  "The next catch-up audits the day again.")
        return AuditReport(audit_date, "failed", cause="unexpected")

    audit_log.info(f"Audit of {audit_date} ({audit_type}): {status}; {notes}")
    if watch.recovered(BATCH_STOPPING_CAUSES):
        alert("The end-of-day audit is running again.")
    new = [f for f in failures if (f.kind, f.ticker, f.fill_id) not in known]
    if new:
        alert(_failure_message(audit_date, new))
    for run in resolved:
        alert(f"Audit failure of {run['audit_date']} resolved ({', '.join(sorted(run['kinds']))}).")
    for run, keys in gone:
        alert(f"Audit problems of {run['audit_date']} resolved: {'; '.join(_key_line(key) for key in keys)}.")
    return AuditReport(audit_date, status, audit_id, tuple(failures), len(recorded),
                       tuple(run["audit_id"] for run in resolved))

def _needs_audit(latest: dict | None) -> bool:
    """Return True for a day with no run, a not_run run, or an unresolved failed run as its newest"""
    if latest is None:
        return True
    return latest["status"] == "not_run" or (latest["status"] == "fail" and latest["resolved_at"] is None)

def days_to_audit(conn, now: datetime, calendar: dict) -> tuple:
    """Return the trading days that still need an audit, oldest first, and the older ones past the cap

    A day needs an audit when it has no run, or its newest run is not_run or an unresolved failure. Days start at
    the first saved trade, order or Alpaca event (the last finished trading day when there are none) and end today once
    AUDIT_MINUTES_AFTER_CLOSE has passed after the close, yesterday's trading day before. Reads only.

    Parameters:
        conn (Connection): An open database connection
        now (datetime): The time now, timezone-aware
        calendar (dict): Trading days from get_calendar

    Returns:
        (days to audit within the newest AUDIT_CATCH_UP_MAX_DAYS trading days, needed days older than that)

    Raises:
        pyodbc.Error if the database can't be read
    """
    today = _new_york_date(now)
    close_at = session_times(calendar, now)[1]
    today_ready = close_at is not None and now >= close_at + timedelta(minutes=AUDIT_MINUTES_AFTER_CLOSE)
    days = [day for day in sorted(calendar) if day < today or (day == today and today_ready)]
    if not days:
        return [], []
    first_activity = get_first_activity_time(conn)
    latest = get_latest_audits(conn)
    first_day = _new_york_date(first_activity) if first_activity else days[-1]
    needed = [day for day in days if day >= first_day and _needs_audit(latest.get(day))]
    recent = set(days[-AUDIT_CATCH_UP_MAX_DAYS:])
    return [day for day in needed if day in recent], [day for day in needed if day not in recent]

def catch_up_audits(conn, broker, now: datetime, calendar: dict, watch: AuditWatch, *, alert=send_critical,
                    notify=send) -> list:
    """Audit every trading day that still needs it (days_to_audit), oldest first

    Called at startup and at the end-of-day audit time. Days past AUDIT_CATCH_UP_MAX_DAYS get one alert. The last
    day also checks shares and cash, unless the market is open. Stops at the first run Alpaca didn't answer or that
    lost the database connection; a day that failed for another reason is left for the next catch-up and the batch
    goes on. Never raises.

    Parameters:
        conn (Connection): An open database connection; commits as it goes
        broker (AlpacaBroker): The broker to ask
        now (datetime): The time now, timezone-aware
        calendar (dict): Trading days from get_calendar, reaching back past the cap
        watch (AuditWatch): What earlier runs remembered
        alert (callable): Sends a critical alert; Discord by default
        notify (callable): Sends (kind, message, asset) like notifications.send, e.g. a manual trade note

    Returns:
        The AuditReport of each run, oldest first
    """
    reports = []
    try:
        market_open_at, close_at = session_times(calendar, now)
        market_open = market_open_at is not None and market_open_at <= now < close_at
        needed, too_old = days_to_audit(conn, now, calendar)
        _cap_alert(too_old, watch, alert)
        for index, day in enumerate(needed):
            report = run_audit(conn, broker, day, now, calendar,
                               check_now=index == len(needed) - 1 and not market_open, watch=watch, alert=alert,
                               notify=notify)
            reports.append(report)
            if report.cause in BATCH_STOPPING_CAUSES:
                break
        if needed and all(report.cause is None for report in reports) and watch.recovered(DAY_CAUSES):
            alert("Every day that couldn't be audited before audits again.")
    except pyodbc.Error as error:
        _rollback(conn)
        audit_log.error(f"Audit catch-up couldn't read the database: {type(error).__name__}: {error}")
        if watch.outage("database"):
            alert(f"The audit catch-up couldn't read which days need an audit: database error "
                  f"({type(error).__name__}: {error}). It tries again at the next startup or end-of-day audit.")
    except Exception as error:
        _rollback(conn)
        audit_log.error(f"Audit catch-up failed: {type(error).__name__}: {error}")
        if watch.outage("unexpected"):
            alert(f"The audit catch-up failed unexpectedly ({type(error).__name__}: {error}). It tries again at the "
                  "next startup or end-of-day audit.")
    return reports

def _cap_alert(too_old: list, watch: AuditWatch, alert):
    """Log days past the catch-up cap; alert once until none are left"""
    if not too_old:
        watch.cap_alerted = False
        return
    audit_log.warning(f"{len(too_old)} trading days older than the catch-up limit weren't audited "
                      f"(oldest {too_old[0]})")
    if not watch.cap_alerted:
        watch.cap_alerted = True
        alert(f"{len(too_old)} trading day(s) older than the {AUDIT_CATCH_UP_MAX_DAYS}-day catch-up limit were "
              f"never audited (oldest {too_old[0]}). Check them by hand.")

def audit_reminders(conn, now: datetime, calendar: dict, watch: AuditWatch, *, alert=send_critical) -> bool:
    """Remind while an audit failure is open or a day couldn't be audited: at the first check after the open, then
    every AUDIT_REPEAT_MINUTES

    Only while the market is open, when blocked buys matter. Days that couldn't be audited are the days within the
    catch-up cap whose newest run is not_run, or that have no run since the first saved activity. Called once per
    cycle. Never raises: a failed check is rolled back and alerted once, and once more when checks work again.

    Parameters:
        conn (Connection): An open database connection
        now (datetime): The time now, timezone-aware
        calendar (dict): Trading days from get_calendar
        watch (AuditWatch): What earlier checks remembered
        alert (callable): Sends a critical alert; Discord by default

    Returns:
        True if a reminder went out
    """
    try:
        market_open_at, close_at = session_times(calendar, now)
        if market_open_at is None or not market_open_at <= now < close_at:
            return False
        if not watch.reminder_due(now, AUDIT_REPEAT_MINUTES):
            return False
        runs = get_open_audits(conn)
        blocked = get_open_failure_tickers(conn, exclude_kinds=NOT_BLOCKING_KINDS)
        needed = days_to_audit(conn, now, calendar)[0]
        latest = get_latest_audits(conn)
        started = get_first_activity_time(conn) is not None
        not_audited = [day for day in needed
                       if (day in latest and latest[day]["status"] == "not_run") or (day not in latest and started)]
    except Exception as error:
        _rollback(conn)
        audit_log.error(f"The audit reminder couldn't check open audit failures: {type(error).__name__}: {error}")
        if not watch.reminder_read_failed:
            watch.reminder_read_failed = True
            alert(f"The audit reminder couldn't check open audit failures ({type(error).__name__}: {error}). Buys "
                  "of tickers with an open failure stay blocked by the risk check; it tries again every cycle.")
        return False
    if watch.reminder_read_failed:
        watch.reminder_read_failed = False
        alert("The audit reminder can check open audit failures again.")
    if not runs and not not_audited:
        return False
    parts = []
    if runs:
        days = ", ".join(sorted({str(run["audit_date"]) for run in runs}))
        block = f"Buys of {', '.join(sorted(blocked))} stay blocked." if blocked else "No buys are blocked."
        parts.append(f"{len(runs)} audit failure(s) still open (days {days}). {block} Resolve by fixing the records "
                     "or setting audit_log.resolved_at.")
    if not_audited:
        parts.append(f"{len(not_audited)} day(s) couldn't be audited yet ({', '.join(map(str, not_audited))}); the "
                     "next catch-up tries again.")
    alert(" ".join(parts))
    watch.reminded(now)
    return True
