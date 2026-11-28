"""
test_audit_end_of_day.py
Scenario tests for the end-of-day audit (AUD-5, 6, 7, 10, 12, 13): every way a position closes lands in the database
exactly once and the audit agrees; and every way the books can go wrong is found, saved, alerted and resolved
"""

#Standard Library
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
import audit.end_of_day as end_of_day
from audit import AuditWatch, audit_reminders, catch_up_audits, days_to_audit, run_audit
from audit_samples import (AFTER_CLOSE, DAY, Alerts, Notes, FakeAuditBroker, dated_activity, fill_activity,
                           trading_calendar)
from fill_samples import CommitCounter, add_bracket, add_sell, add_strategy, fill, order, positions
from fills.events import from_activity
from fills.handler import HandleResult, process_update
from storage.fills import save_broker_event
from risk_samples import as_admin
from audit.matching import day_window
from storage.audit import get_open_failure_tickers, resolve_audits

CALENDAR = trading_calendar()
BUY_AT, SELL_AT = "2026-11-02T14:31:04Z", "2026-11-02T15:10:00Z"

@pytest.fixture
def conn(bot_conn):
    return CommitCounter(bot_conn)

@pytest.fixture
def strategy_id(bot_conn):
    return add_strategy(bot_conn)

@pytest.fixture
def alerts():
    return Alerts()

@pytest.fixture
def notes():
    return Notes()

def stream(conn, update):
    """Handle one update the way the fill stream does, a second after it happened"""
    return process_update(conn, update, update.event_at + timedelta(seconds=1))

def buy_fill(quantity=10, filled=None, price="5.00", execution_id="exec-buy", at=BUY_AT):
    """Return the bracket buy's fill (10 shares at 5.00 unless told otherwise)"""
    return fill("alpaca-buy-1", quantity, Decimal(price), execution_id, filled=filled, at=at)

def leg_fill(leg="limit", price="5.20", execution_id="exec-leg"):
    """Return a fill of the buy's take-profit (limit) or stop-loss (stop) leg"""
    return fill(f"alpaca-{leg}-1", 10, Decimal(price), execution_id, side="sell", order_type=leg, at=SELL_AT)

def audit(conn, broker, alerts, notes, audit_date=DAY, now=AFTER_CLOSE, watch=None, check_now=True):
    """Run one audit with the test calendar and recorded alerts"""
    return run_audit(conn, broker, audit_date, now, CALENDAR, check_now=check_now, watch=watch, alert=alerts,
                     notify=notes)

def audit_rows(conn):
    """Return every audit_log row, oldest first"""
    return conn.execute("SELECT * FROM audit_log ORDER BY audit_id").fetchall()

def failure_rows(conn):
    """Return every audit_failures row as (kind, ticker, alpaca_fill_id), oldest first"""
    return conn.execute("SELECT kind, ticker, alpaca_fill_id FROM audit_failures ORDER BY audit_failure_id").fetchall()

def round_trip(conn, strategy_id, leg="limit"):
    """Fill a bracket buy and one of its legs through the stream; return the two updates"""
    add_bracket(conn, strategy_id)
    updates = (buy_fill(), leg_fill(leg))
    for update in updates:
        stream(conn, update)
    return updates

@pytest.mark.parametrize("leg, exit_reason", [("limit", "take_profit"), ("stop", "stop_loss")])
def test_bracket_exit_lands_once_and_the_audit_passes(conn, strategy_id, alerts, notes, leg, exit_reason):
    """Close through the take-profit or stop-loss leg; the audit finds both fills and nothing wrong"""
    updates = round_trip(conn, strategy_id, leg)

    report = audit(conn, FakeAuditBroker([fill_activity(u) for u in updates]), alerts, notes)

    row, = audit_rows(conn)
    assert (report.status, row.status, row.audit_type, row.fills_at_alpaca, row.fills_in_db, row.missing_in_db,
            row.missing_at_alpaca, row.share_mismatches) == ("pass", "pass", "end_of_day", 2, 2, 0, 0, 0)
    assert [(p.status, p.exit_reason) for p in positions(conn)] == [("closed", exit_reason)]
    assert alerts.sent == []

def test_end_of_day_close_lands_once_and_the_audit_passes(conn, strategy_id, alerts, notes):
    """Close with E3's end-of-day market sell; the audit agrees"""
    ids = add_bracket(conn, strategy_id, legs=False)
    buy = buy_fill()
    stream(conn, buy)
    add_sell(conn, strategy_id, order(conn, ids["buy"]).position_id)
    sell = fill("alpaca-sell-1", 10, Decimal("5.10"), "exec-sell", side="sell", at=SELL_AT)
    stream(conn, sell)

    report = audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(sell)]), alerts, notes)

    assert report.status == "pass"
    assert [(p.status, p.exit_reason) for p in positions(conn)] == [("closed", "end_of_day")]

def test_partial_fills_land_as_one_position_and_the_audit_passes(conn, strategy_id, alerts, notes):
    """Fill the buy in two parts, then exit; every part is one trade and one activity"""
    add_bracket(conn, strategy_id)
    updates = (buy_fill(4, filled=4, execution_id="exec-buy-a"),
               buy_fill(6, filled=10, execution_id="exec-buy-b", at="2026-11-02T14:31:09Z"), leg_fill())
    for update in updates:
        stream(conn, update)

    report = audit(conn, FakeAuditBroker([fill_activity(u) for u in updates]), alerts, notes)

    assert (report.status, audit_rows(conn)[0].fills_at_alpaca) == ("pass", 3)
    assert [(p.entry_quantity, p.status) for p in positions(conn)] == [(10, "closed")]

def test_manual_trade_lands_under_manual_and_the_audit_passes(conn, alerts, notes):
    """Record a dashboard buy and sell under the manual strategy; the audit agrees"""
    manual_buy = fill("dash-buy", 3, Decimal("7.00"), "exec-dash-buy", at=BUY_AT)
    manual_sell = fill("dash-sell", 3, Decimal("7.10"), "exec-dash-sell", side="sell", at=SELL_AT)
    for update in (manual_buy, manual_sell):
        process_update(conn, update, update.event_at + timedelta(minutes=5))

    report = audit(conn, FakeAuditBroker([fill_activity(manual_buy), fill_activity(manual_sell)]), alerts, notes)

    assert report.status == "pass"
    assert [(p.status, p.exit_reason) for p in positions(conn)] == [("closed", "manual")]

def test_fill_the_catch_up_found_after_a_restart_is_counted(conn, strategy_id, alerts, notes):
    """Count a fill the stream missed (bot restarting) and the fill stream's catch-up recorded"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    process_update(conn, from_activity(fill_activity(target)), target.event_at + timedelta(minutes=1))

    report = audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target)]), alerts, notes)

    row, = audit_rows(conn)
    assert (report.status, row.catch_up_fills, row.audit_fills, row.missing_in_db) == ("pass", 1, 0, 0)

def test_fill_both_missed_is_recorded_by_the_audit(conn, strategy_id, alerts, notes):
    """Record a fill the stream and the catch-up both missed, count it, alert once and still pass"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)

    report = audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target)]), alerts, notes)

    row, = audit_rows(conn)
    assert (report.status, row.missing_in_db, row.audit_fills, row.fills_in_db) == ("pass", 1, 1, 2)
    assert [(p.status, p.exit_reason) for p in positions(conn)] == [("closed", "take_profit")]
    assert conn.execute("SELECT COUNT(*) FROM broker_events WHERE event_type = 'audit_fill' "
                        "AND execution_id = 'exec-leg'").fetchone()[0] == 1
    assert len(alerts.sent) == 1 and "recorded 1 fill" in alerts.sent[0]

def test_every_activity_is_saved_raw_once(conn, strategy_id, alerts, notes):
    """Save fills and other activities raw; a second run of the same day saves nothing twice"""
    updates = round_trip(conn, strategy_id)
    broker = FakeAuditBroker([fill_activity(u) for u in updates] + [dated_activity("FEE", "-0.02")])

    audit(conn, broker, alerts, notes)
    audit(conn, broker, alerts, notes)

    types = conn.execute("SELECT activity_type FROM account_activities ORDER BY account_activity_id").fetchall()
    assert [row.activity_type for row in types] == ["FILL", "FILL", "FEE"]

def test_trade_alpaca_never_made_fails_and_blocks_the_ticker(conn, strategy_id, alerts, notes):
    """Fail a day whose database has a fill Alpaca doesn't list; block that ticker's buys and alert"""
    buy, target = round_trip(conn, strategy_id)

    report = audit(conn, FakeAuditBroker([fill_activity(buy)]), alerts, notes)

    assert (report.status, audit_rows(conn)[0].missing_at_alpaca) == ("fail", 1)
    assert [tuple(row) for row in failure_rows(conn)] == [("missing_at_alpaca", "AAPL", "exec-leg")]
    assert get_open_failure_tickers(conn, exclude_kinds=end_of_day.NOT_BLOCKING_KINDS) == frozenset({"AAPL"})
    assert len(alerts.sent) == 1 and "AAPL" in alerts.sent[0]

def test_trade_alpaca_never_made_stays_open_after_a_re_audit(conn, strategy_id, alerts, notes):
    """Keep a failure that can't fix itself open in the newest run; the older run it replaces is closed"""
    buy, _ = round_trip(conn, strategy_id)
    broker = FakeAuditBroker([fill_activity(buy)])
    audit(conn, broker, alerts, notes)

    report = audit(conn, broker, alerts, notes)

    older, newer = audit_rows(conn)
    assert (older.resolved_at is not None, newer.resolved_at) == (True, None)
    assert report.resolved == ()
    assert get_open_failure_tickers(conn, exclude_kinds=end_of_day.NOT_BLOCKING_KINDS) == frozenset({"AAPL"})

def test_price_mismatch_fails_then_a_correction_resolves_it(conn, strategy_id, alerts, notes):
    """Fail on a different fill price; a correction row with Alpaca's price passes the re-audit and resolves it"""
    buy, target = round_trip(conn, strategy_id)
    broker = FakeAuditBroker([fill_activity(buy), fill_activity(target, price="5.21")])
    audit(conn, broker, alerts, notes)
    wrong = conn.execute("SELECT * FROM trades WHERE alpaca_fill_id = 'exec-leg'").fetchone()
    conn.execute("INSERT INTO trades (side, quantity, filled_at, fill_price, time_frame, exit_reason, position_id, "
                 "order_id, corrects_trade_id) VALUES ('sell', 10, ?, 5.21, '15Min', 'take_profit', ?, ?, ?)",
                 (wrong.filled_at, wrong.position_id, wrong.order_id, wrong.trade_id))

    report = audit(conn, broker, alerts, notes)

    first, second = audit_rows(conn)
    assert (first.status, first.price_mismatches, second.status) == ("fail", 1, "pass")
    assert first.resolved_at is not None and report.resolved == (first.audit_id,)
    assert "resolved" in alerts.sent[-1]

def test_quantity_mismatch_fails(conn, strategy_id, alerts, notes):
    """Fail a day whose fill has a different share count at Alpaca"""
    buy, target = round_trip(conn, strategy_id)

    audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target, quantity=9)]), alerts, notes)

    assert audit_rows(conn)[0].quantity_mismatches == 1
    assert [row.kind for row in failure_rows(conn)] == ["quantity_mismatch"]

def test_order_whose_fills_dont_add_up_fails(conn, strategy_id, alerts, notes):
    """Fail on an order whose filled quantity isn't the sum of its trades"""
    ids = add_bracket(conn, strategy_id)
    buy = buy_fill()
    stream(conn, buy)
    stream(conn, leg_fill())
    conn.execute("UPDATE orders SET filled_quantity = 3 WHERE order_id = ?", ids["stop"])

    audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(leg_fill())]), alerts, notes)

    assert [tuple(row) for row in failure_rows(conn)] == [("order_fill_mismatch", "AAPL", None)]

def test_repeated_failure_alerts_only_the_first_time(conn, strategy_id, alerts, notes):
    """Send no new alert when a re-audit finds the same open problem again (reminders cover it)"""
    buy, _ = round_trip(conn, strategy_id)
    broker = FakeAuditBroker([fill_activity(buy)])
    audit(conn, broker, alerts, notes)

    audit(conn, broker, alerts, notes)

    assert len(alerts.sent) == 1

def test_alpaca_down_saves_a_not_run_row_and_alerts_once(conn, alerts, notes):
    """Save not_run with a reason plus a bot_events row; a second failure in the same outage stays quiet"""
    watch = AuditWatch()
    broker = FakeAuditBroker(error="read timed out")

    first = audit(conn, broker, alerts, notes, watch=watch)
    audit(conn, broker, alerts, notes, watch=watch)

    rows = audit_rows(conn)
    assert (first.status, [r.status for r in rows]) == ("not_run", ["not_run", "not_run"])
    assert "read timed out" in rows[0].not_run_reason
    assert conn.execute("SELECT COUNT(*) FROM bot_events WHERE event_type = 'audit_not_run'").fetchone()[0] == 2
    assert len(alerts.sent) == 1

def test_audit_after_an_outage_says_it_runs_again(conn, alerts, notes):
    """Say the audit runs again after an outage alert"""
    watch = AuditWatch()
    audit(conn, FakeAuditBroker(error="read timed out"), alerts, notes, watch=watch)

    report = audit(conn, FakeAuditBroker(), alerts, notes, watch=watch)

    assert report.status == "pass"
    assert alerts.sent[-1] == "The end-of-day audit is running again."

def test_failure_after_the_run_row_is_written_rolls_the_run_back(conn, alerts, notes, monkeypatch):
    """Roll back a half-saved run when resolving fails after the row was inserted; only the activities stay committed"""
    monkeypatch.setattr(end_of_day, "resolve_audits", broken_database)

    report = audit(conn, FakeAuditBroker([dated_activity("FEE", "-0.02")]), alerts, notes)

    assert (report.status, conn.commits, conn.rollbacks) == ("failed", 1, 1)

def test_activities_are_committed_before_anything_can_fail(conn, alerts, notes, monkeypatch):
    """Commit Alpaca's activities raw before matching, so an error later still leaves them saved"""
    monkeypatch.setattr(end_of_day, "match_fills", broken_match)

    audit(conn, FakeAuditBroker([dated_activity("FEE", "-0.02")]), alerts, notes)

    assert (conn.commits, conn.rollbacks) == (1, 1)
    assert conn.execute("SELECT COUNT(*) FROM account_activities").fetchone()[0] == 1

def test_database_down_saves_nothing_and_alerts(conn, alerts, notes, monkeypatch):
    """Leave no row and send one alert when the database fails mid-audit; the catch-up finds the day later"""
    def broken(*args, **kwargs):
        raise pyodbc.OperationalError("08S01", "Communication link failure")
    monkeypatch.setattr(end_of_day, "insert_audit", broken)

    report = audit(conn, FakeAuditBroker(), alerts, notes)

    assert (report.status, report.audit_id) == ("failed", None)
    assert conn.rollbacks >= 1
    assert len(alerts.sent) == 1 and "database" in alerts.sent[0]

def test_unexpected_error_saves_nothing_alerts_and_never_raises(conn, alerts, notes, monkeypatch):
    """Catch an error nobody expected (e.g. an odd activity from Alpaca): roll back, alert, carry on"""
    def broken(*args, **kwargs):
        raise KeyError("symbol")
    monkeypatch.setattr(end_of_day, "match_fills", broken)

    report = audit(conn, FakeAuditBroker(), alerts, notes)

    assert (report.status, audit_rows(conn)) == ("failed", [])
    assert len(alerts.sent) == 1 and "KeyError" in alerts.sent[0]
    assert "Nothing was saved" not in alerts.sent[0]

def test_open_position_at_the_close_is_a_share_mismatch_that_blocks_nothing(conn, strategy_id, alerts, notes):
    """Record a share mismatch at the close without blocking buys (A2 blocks live); the next match resolves it"""
    add_bracket(conn, strategy_id)
    buy = buy_fill()
    stream(conn, buy)
    audit(conn, FakeAuditBroker([fill_activity(buy)]), alerts, notes)

    audit(conn, FakeAuditBroker([fill_activity(buy)], positions={"AAPL": 10}), alerts, notes)

    first, second = audit_rows(conn)
    assert (first.status, first.share_mismatches, second.status) == ("fail", 1, "pass")
    assert first.resolved_at is not None
    assert get_open_failure_tickers(conn, exclude_kinds=end_of_day.NOT_BLOCKING_KINDS) == frozenset()

def test_past_day_without_the_now_checks_leaves_shares_and_cash_empty(conn, alerts, notes):
    """Skip shares and cash when check_now is off (an earlier day in a catch-up batch)"""

    audit(conn, FakeAuditBroker(), alerts, notes, check_now=False)

    row, = audit_rows(conn)
    assert (row.share_mismatches, row.alpaca_cash, row.expected_cash) == (None, None, None)

def seed_cash_baseline(conn, cash="1000"):
    """Save an earlier passing run that read Alpaca's cash, as the starting point"""
    conn.execute("INSERT INTO audit_log (audit_date, audit_type, run_at, fills_at_alpaca, fills_in_db, missing_in_db, "
                 "missing_at_alpaca, [status], catch_up_fills, audit_fills, price_mismatches, quantity_mismatches, "
                 "share_mismatches, alpaca_cash, expected_cash) VALUES ('2026-10-30', 'end_of_day', "
                 "'2026-10-30 21:15', 0, 0, 0, 0, 'pass', 0, 0, 0, 0, 0, ?, ?)", (cash, cash))

def test_first_cash_check_sets_the_starting_point(conn, alerts, notes):
    """Use Alpaca's cash as the expected cash on the very first check"""

    audit(conn, FakeAuditBroker(cash="987.65"), alerts, notes)

    row, = audit_rows(conn)
    assert (row.status, row.alpaca_cash, row.expected_cash) == ("pass", Decimal("987.6500"), Decimal("987.6500"))

def test_cash_explained_by_fills_and_a_fee_passes(conn, strategy_id, alerts, notes):
    """Pass when Alpaca's cash = start + fills (10 x 5.20 - 10 x 5.00) + the day's fee"""
    seed_cash_baseline(conn)
    updates = round_trip(conn, strategy_id)
    broker = FakeAuditBroker([fill_activity(u) for u in updates] + [dated_activity("FEE", "-0.02")], cash="1001.98")

    report = audit(conn, broker, alerts, notes)

    assert report.status == "pass"
    assert audit_rows(conn)[-1].expected_cash == Decimal("1001.9800")

def test_unexplained_cash_fails_without_blocking_buys(conn, strategy_id, alerts, notes):
    """Fail a cash difference nothing explains, list it in the alert, and block no ticker"""
    seed_cash_baseline(conn)
    updates = round_trip(conn, strategy_id)

    audit(conn, FakeAuditBroker([fill_activity(u) for u in updates], cash="1007.00"), alerts, notes)

    assert [tuple(row) for row in failure_rows(conn)] == [("cash", None, None)]
    assert get_open_failure_tickers(conn, exclude_kinds=end_of_day.NOT_BLOCKING_KINDS) == frozenset()
    assert "cash" in alerts.sent[0].lower() and "5.00" in alerts.sent[0] and "No buys are blocked" in alerts.sent[0]

def test_owners_adjustment_explains_cash_and_resolves_the_failure(conn, strategy_id, alerts, notes):
    """Pass once the owner adds an adjustment for the unexplained cash, and resolve the earlier failure"""
    seed_cash_baseline(conn)
    updates = round_trip(conn, strategy_id)
    broker = FakeAuditBroker([fill_activity(u) for u in updates], cash="1007.00")
    audit(conn, broker, alerts, notes)
    as_admin(conn, "INSERT INTO cash_adjustments (amount, effective_date, reason, note) "
                   "VALUES (5, '2026-11-02', 'deposit', 'transfer Alpaca listed late')")

    report = audit(conn, broker, alerts, notes)

    failed = audit_rows(conn)[1]
    assert (report.status, report.resolved) == ("pass", (failed.audit_id,))
    assert "resolved" in alerts.sent[-1]

def test_catch_up_audits_each_missed_trading_day_skipping_the_holiday(conn, strategy_id, alerts, notes):
    """Audit every trading day since the first order and trade, oldest first, skipping Thanksgiving and today before
    the close"""
    add_bracket(conn, strategy_id)
    as_admin(conn, "UPDATE orders SET submitted_at = '2026-11-25 14:59'")
    stream(conn, buy_fill(at="2026-11-25T15:00:00Z"))
    market_open = datetime(2026, 11, 30, 15, tzinfo=timezone.utc)

    reports = catch_up_audits(conn, FakeAuditBroker(positions={"AAPL": 10}), market_open, CALENDAR, AuditWatch(),
                              alert=alerts, notify=notes)

    rows = audit_rows(conn)
    assert [r.audit_date for r in rows] == [date(2026, 11, 25), date(2026, 11, 27)]
    assert {r.audit_type for r in rows} == {"catch_up"}
    assert [r.share_mismatches for r in rows] == [None, None]
    assert len(reports) == 2

def test_catch_up_after_the_close_audits_today_with_the_now_checks(conn, alerts, notes):
    """Audit today as end_of_day once the audit time has passed, with shares and cash"""

    catch_up_audits(conn, FakeAuditBroker(), AFTER_CLOSE, CALENDAR, AuditWatch(), alert=alerts, notify=notes)

    row, = audit_rows(conn)
    assert (row.audit_date, row.audit_type, row.share_mismatches) == (DAY, "end_of_day", 0)

def test_catch_up_redoes_only_days_with_an_open_failure(conn, strategy_id, alerts, notes):
    """Re-audit a day whose newest run is an unresolved failure; leave a passed day and a day resolved by hand alone"""
    add_bracket(conn, strategy_id)
    buy = buy_fill(at="2026-10-29T15:00:00Z")
    stream(conn, buy)
    broken = {"id": "20261030150000000::broken", "activity_type": "FILL"}
    audit(conn, FakeAuditBroker([fill_activity(buy)]), alerts, notes, audit_date=date(2026, 10, 29), check_now=False)
    by_hand = audit(conn, FakeAuditBroker([broken]), alerts, notes, audit_date=date(2026, 10, 30), check_now=False)
    resolve_audits(conn, [by_hand.audit_id])
    audit(conn, FakeAuditBroker([{**broken, "id": "20261102150000000::broken"}]), alerts, notes, check_now=False)
    next_morning = datetime(2026, 11, 3, 13, tzinfo=timezone.utc)

    catch_up_audits(conn, FakeAuditBroker(positions={"AAPL": 10}), next_morning, CALENDAR, AuditWatch(), alert=alerts,
                    notify=notes)

    assert [r.audit_date for r in audit_rows(conn)] == [date(2026, 10, 29), date(2026, 10, 30), DAY, DAY]

def test_catch_up_stops_at_the_cap_and_alerts_once(conn, strategy_id, alerts, notes, monkeypatch):
    """Audit only the newest days within the cap and alert once about the older ones"""
    monkeypatch.setattr(end_of_day, "AUDIT_CATCH_UP_MAX_DAYS", 3)
    add_bracket(conn, strategy_id)
    stream(conn, buy_fill(at="2026-10-20T15:00:00Z"))
    watch = AuditWatch()

    catch_up_audits(conn, FakeAuditBroker(positions={"AAPL": 10}), AFTER_CLOSE, CALENDAR, watch, alert=alerts,
                    notify=notes)
    catch_up_audits(conn, FakeAuditBroker(error="down"), AFTER_CLOSE, CALENDAR, watch, alert=alerts, notify=notes)

    assert [r.audit_date for r in audit_rows(conn)][:3] == [date(2026, 10, 29), date(2026, 10, 30), DAY]
    assert sum("older than" in message for message in alerts.sent) == 1

def test_catch_up_stops_the_batch_when_alpaca_is_down_and_redoes_it_next_time(conn, strategy_id, alerts, notes):
    """Write one not_run row, leave the later days, and audit them all at the next catch-up"""
    add_bracket(conn, strategy_id)
    buy = buy_fill(at="2026-10-28T15:00:00Z")
    stream(conn, buy)
    watch = AuditWatch()
    catch_up_audits(conn, FakeAuditBroker(error="down"), AFTER_CLOSE, CALENDAR, watch, alert=alerts, notify=notes)
    first = [(r.audit_date, r.status) for r in audit_rows(conn)]

    catch_up_audits(conn, FakeAuditBroker([fill_activity(buy)], positions={"AAPL": 10}), AFTER_CLOSE, CALENDAR, watch,
                    alert=alerts, notify=notes)

    assert first == [(date(2026, 10, 28), "not_run")]
    assert [(r.audit_date, r.status) for r in audit_rows(conn)][1:] == [
        (date(2026, 10, 28), "pass"), (date(2026, 10, 29), "pass"), (date(2026, 10, 30), "pass"), (DAY, "pass")]

MARKET_OPEN = datetime(2026, 11, 3, 14, 31, tzinfo=timezone.utc)

def open_failure(conn, strategy_id, alerts, notes):
    """Leave a failed run open on DAY: the database has a sell Alpaca never made (AAPL)"""
    buy, _ = round_trip(conn, strategy_id)
    audit(conn, FakeAuditBroker([fill_activity(buy)]), alerts, notes)

def test_reminder_goes_out_at_the_open_then_hourly(conn, strategy_id, alerts, notes):
    """Remind at the first check after the open, stay quiet within the hour, remind again after it"""
    open_failure(conn, strategy_id, alerts, notes)
    watch, reminders = AuditWatch(), Alerts()

    sent = [audit_reminders(conn, MARKET_OPEN + timedelta(minutes=m), CALENDAR, watch, alert=reminders)
            for m in (0, 30, 61)]

    assert sent == [True, False, True]
    assert "AAPL" in reminders.sent[0]

def test_no_reminder_outside_market_hours(conn, strategy_id, alerts, notes):
    """Send no reminder outside market hours, when nothing is being bought"""
    open_failure(conn, strategy_id, alerts, notes)

    assert audit_reminders(conn, AFTER_CLOSE + timedelta(hours=2), CALENDAR, AuditWatch(), alert=Alerts()) is False

def test_no_reminder_without_open_failures(conn):
    """Send no reminder when nothing is open or missing"""
    assert audit_reminders(conn, MARKET_OPEN, CALENDAR, AuditWatch(), alert=Alerts()) is False

def test_restart_reminds_at_once_from_the_saved_failure(conn, strategy_id, alerts, notes):
    """Rebuild from audit_log after a restart: a fresh watch reminds on its first check in market hours"""
    open_failure(conn, strategy_id, alerts, notes)
    audit_reminders(conn, MARKET_OPEN, CALENDAR, AuditWatch(), alert=Alerts())

    assert audit_reminders(conn, MARKET_OPEN + timedelta(minutes=5), CALENDAR, AuditWatch(), alert=Alerts()) is True

def save_unreadable(conn, execution_id=None):
    """Save a fill message the stream couldn't read, the way FillStream._save_unreadable does"""
    save_broker_event(conn, event_type="fill", alpaca_order_id=None, client_order_id=None, execution_id=execution_id,
                      ticker=None, event_at=None, raw_json='{"event": "fill", "execution_id": "garbled"}')

def test_unreadable_saved_fill_does_not_stop_the_audit(conn, strategy_id, alerts, notes):
    """Record a missed fill even though an unreadable fill message sits unhandled in broker_events"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    save_unreadable(conn)

    report = audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target)]), alerts, notes)

    assert (report.status, report.audit_fills) == ("pass", 1)

def test_unreadable_saved_row_of_the_missing_fill_falls_back_to_alpacas_activity(conn, strategy_id, alerts, notes):
    """Record the fill from Alpaca's activity when its own saved message can't be read"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    save_unreadable(conn, execution_id="exec-leg")

    report = audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target)]), alerts, notes)

    assert (report.status, report.audit_fills) == ("pass", 1)
    assert [(p.status, p.exit_reason) for p in positions(conn)] == [("closed", "take_profit")]

def test_unreadable_activity_is_a_failure_and_the_rest_is_still_audited(conn, strategy_id, alerts, notes):
    """Save a failure for an activity that can't be read, alert once, and still match every other fill"""
    updates = round_trip(conn, strategy_id)
    broken = {"id": "20261102151000000::broken", "activity_type": "FILL"}

    report = audit(conn, FakeAuditBroker([fill_activity(u) for u in updates] + [broken]), alerts, notes)

    row, = audit_rows(conn)
    assert (report.status, row.fills_at_alpaca, row.fills_in_db) == ("fail", 2, 2)
    assert [tuple(r) for r in failure_rows(conn)] == [("unreadable_activity", None, "20261102151000000::broken")]
    assert len(alerts.sent) == 1 and "No buys are blocked" in alerts.sent[0]

def broken_match(*args, **kwargs):
    """Stand in for match_fills and raise an error nobody expected"""
    raise KeyError("symbol")

def test_repeating_unexpected_error_alerts_once_per_outage(conn, alerts, notes, monkeypatch):
    """Alert the first time an unexpected error stops the audit, not on every run while it keeps happening"""
    monkeypatch.setattr(end_of_day, "match_fills", broken_match)
    watch = AuditWatch()

    audit(conn, FakeAuditBroker(), alerts, notes, watch=watch)
    audit(conn, FakeAuditBroker(), alerts, notes, watch=watch)

    assert len(alerts.sent) == 1

def test_new_cause_alerts_during_another_outage(conn, alerts, notes, monkeypatch):
    """Alert again when the database fails while an Alpaca outage was already alerted: the cause changed"""
    watch = AuditWatch()
    audit(conn, FakeAuditBroker(error="read timed out"), alerts, notes, watch=watch)
    monkeypatch.setattr(end_of_day, "insert_audit", broken_database)

    audit(conn, FakeAuditBroker(), alerts, notes, watch=watch)

    assert len(alerts.sent) == 2 and "database" in alerts.sent[1]

def broken_database(*args, **kwargs):
    """Stand in for a storage call and raise a lost-connection database error"""
    raise pyodbc.OperationalError("08S01", "Communication link failure")

def test_recorded_fill_alert_survives_a_failed_save(conn, strategy_id, alerts, notes, monkeypatch):
    """Send the "recorded fills" alert even when saving the run fails afterwards; the fills are already committed"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    monkeypatch.setattr(end_of_day, "insert_audit", broken_database)

    audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target)]), alerts, notes)

    assert any("recorded 1 fill" in message for message in alerts.sent)

def test_rerun_still_counts_the_fills_an_earlier_audit_recorded(conn, strategy_id, alerts, notes, monkeypatch):
    """Count missed fills from what audits saved that day, so a run after a failed save still reports them"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    broker = FakeAuditBroker([fill_activity(buy), fill_activity(target)])
    with monkeypatch.context() as patch:
        patch.setattr(end_of_day, "insert_audit", broken_database)
        audit(conn, broker, alerts, notes)

    audit(conn, broker, alerts, notes)

    row, = audit_rows(conn)
    assert (row.missing_in_db, row.audit_fills) == (1, 1)

def test_not_run_save_failure_is_logged_even_when_already_alerted(conn, alerts, notes, monkeypatch, caplog):
    """Log the database error behind a failed not_run save, even when the outage alert already went out"""
    watch = AuditWatch()
    audit(conn, FakeAuditBroker(error="down"), alerts, notes, watch=watch)
    monkeypatch.setattr(end_of_day, "insert_not_run", broken_database)

    audit(conn, FakeAuditBroker(error="down"), alerts, notes, watch=watch)

    assert "OperationalError" in caplog.text

def test_unreadable_alpaca_answer_is_a_not_run(conn, alerts, notes):
    """Save not_run when Alpaca's answer can't be read at all (not only when it doesn't answer)"""
    class GarbledBroker(FakeAuditBroker):
        def get_activities(self, since, until):
            raise ValueError("Expecting value: line 1 column 1")

    report = audit(conn, GarbledBroker(), alerts, notes)

    assert (report.status, audit_rows(conn)[0].status) == ("not_run", "not_run")

def test_missing_cash_skips_only_the_cash_check(conn, alerts, notes):
    """Audit the fills and shares when Alpaca sends no cash; leave the cash check empty and say so in the notes"""

    report = audit(conn, FakeAuditBroker(cash=None), alerts, notes)

    row, = audit_rows(conn)
    assert (report.status, row.alpaca_cash, row.share_mismatches) == ("pass", None, 0)
    assert "cash not checked" in row.notes

def test_catch_up_never_raises(conn, alerts, notes, monkeypatch):
    """Return no reports and alert once when something unexpected breaks the catch-up, so startup goes on"""
    def broken(*args, **kwargs):
        raise RuntimeError("calendar is empty")
    monkeypatch.setattr(end_of_day, "days_to_audit", broken)

    reports = catch_up_audits(conn, FakeAuditBroker(), AFTER_CLOSE, CALENDAR, AuditWatch(), alert=alerts, notify=notes)

    assert reports == [] and len(alerts.sent) == 1 and "RuntimeError" in alerts.sent[0]

def test_catch_up_database_failure_says_it_couldnt_read(conn, alerts, notes, monkeypatch):
    """Say the catch-up couldn't read which days need an audit, not that a day's audit couldn't save"""
    monkeypatch.setattr(end_of_day, "days_to_audit", broken_database)

    catch_up_audits(conn, FakeAuditBroker(), AFTER_CLOSE, CALENDAR, AuditWatch(), alert=alerts, notify=notes)

    assert "couldn't read which days need an audit" in alerts.sent[0]

def test_reminder_never_raises(conn, monkeypatch):
    """Return False when something unexpected breaks the reminder"""
    def broken(*args, **kwargs):
        raise RuntimeError("bad row")
    monkeypatch.setattr(end_of_day, "get_open_audits", broken)

    assert audit_reminders(conn, MARKET_OPEN, CALENDAR, AuditWatch(), alert=Alerts()) is False

NEXT_DAY, NEXT_CLOSE = date(2026, 11, 3), datetime(2026, 11, 3, 21, 30, tzinfo=timezone.utc)

def open_runs(conn):
    """Return the ids of the failed runs still open"""
    return conn.execute("SELECT audit_id FROM v_open_audit_failures").fetchall()

def test_lasting_cash_difference_alerts_once_and_keeps_one_open_run(conn, strategy_id, alerts, notes):
    """Alert a cash difference once; the next day's run that finds it again replaces the old run quietly"""
    seed_cash_baseline(conn)
    updates = round_trip(conn, strategy_id)
    audit(conn, FakeAuditBroker([fill_activity(u) for u in updates], cash="1007.00"), alerts, notes)

    audit(conn, FakeAuditBroker(cash="1007.00"), alerts, notes, audit_date=NEXT_DAY, now=NEXT_CLOSE)

    assert len(alerts.sent) == 1
    assert len(open_runs(conn)) == 1

def test_lasting_share_mismatch_alerts_once(conn, strategy_id, alerts, notes):
    """Alert a share mismatch once even though each day's run finds it again"""
    add_bracket(conn, strategy_id)
    buy = buy_fill()
    stream(conn, buy)
    audit(conn, FakeAuditBroker([fill_activity(buy)]), alerts, notes)

    audit(conn, FakeAuditBroker(), alerts, notes, audit_date=NEXT_DAY, now=NEXT_CLOSE)

    assert len(alerts.sent) == 1

def test_re_audit_without_the_now_checks_keeps_an_older_cash_failure_open(conn, strategy_id, alerts, notes):
    """Keep the cash problem open when a re-audit fixes the fills but skips cash: it moves to the re-audit's run"""
    seed_cash_baseline(conn)
    buy, target = round_trip(conn, strategy_id)
    audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target, price="5.21")], cash="1007.00"), alerts,
          notes)
    wrong = conn.execute("SELECT * FROM trades WHERE alpaca_fill_id = 'exec-leg'").fetchone()
    conn.execute("INSERT INTO trades (side, quantity, filled_at, fill_price, time_frame, exit_reason, position_id, "
                 "order_id, corrects_trade_id) VALUES ('sell', 10, ?, 5.21, '15Min', 'take_profit', ?, ?, ?)",
                 (wrong.filled_at, wrong.position_id, wrong.order_id, wrong.trade_id))

    audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target, price="5.21")]), alerts, notes,
          check_now=False)

    open_run, = open_runs(conn)
    kinds = conn.execute("SELECT kind FROM audit_failures WHERE audit_id = ?", open_run.audit_id).fetchall()
    assert (audit_rows(conn)[1].resolved_at is not None, [row.kind for row in kinds]) == (True, ["cash"])

def test_clean_audit_of_the_next_day_keeps_an_earlier_days_failure_open(conn, strategy_id, alerts, notes):
    """Keep a day's fill failure (and its ticker block) open when only a different day is audited cleanly"""
    open_failure(conn, strategy_id, alerts, notes)

    report = audit(conn, FakeAuditBroker(), alerts, notes, audit_date=NEXT_DAY, now=NEXT_CLOSE)

    assert (audit_rows(conn)[0].resolved_at, report.resolved) == (None, ())
    assert get_open_failure_tickers(conn, exclude_kinds=end_of_day.NOT_BLOCKING_KINDS) == frozenset({"AAPL"})

def test_not_run_re_audit_never_resolves_the_days_failure(conn, strategy_id, alerts, notes):
    """Keep a day's failure open after a not_run re-audit of that day, even when a later run resolves others"""
    open_failure(conn, strategy_id, alerts, notes)
    audit(conn, FakeAuditBroker(error="down"), alerts, notes)

    audit(conn, FakeAuditBroker(), alerts, notes, audit_date=NEXT_DAY, now=NEXT_CLOSE)

    assert audit_rows(conn)[0].resolved_at is None
    assert get_open_failure_tickers(conn, exclude_kinds=end_of_day.NOT_BLOCKING_KINDS) == frozenset({"AAPL"})

def test_fill_the_audit_cant_record_fails_the_day_and_blocks_the_ticker(conn, strategy_id, alerts, notes,
                                                                         monkeypatch):
    """Fail the day with missing_in_db, block the ticker and pass on the handler's alert when recording fails"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    monkeypatch.setattr(end_of_day, "process_update",
                        lambda *args, **kwargs: HandleResult("failed", [("critical", "Couldn't handle a fill", None)]))

    report = audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target)]), alerts, notes)

    row, = audit_rows(conn)
    assert (report.status, row.missing_in_db, row.audit_fills) == ("fail", 1, 0)
    assert [tuple(r) for r in failure_rows(conn)] == [("missing_in_db", "AAPL", "exec-leg"),
                                                       ("share_mismatch", "AAPL", None)]
    assert "Couldn't handle a fill" in alerts.sent
    assert not any("recorded" in message for message in alerts.sent)
    assert get_open_failure_tickers(conn, exclude_kinds=end_of_day.NOT_BLOCKING_KINDS) == frozenset({"AAPL"})

def test_activities_are_asked_for_from_five_trading_days_back(conn, alerts, notes):
    """Ask Alpaca for activities from ACTIVITY_LOOKBACK_DAYS trading days back (over the weekend) to the day's end"""
    broker = FakeAuditBroker()

    audit(conn, broker, alerts, notes)

    assert broker.calls == [("get_activities", day_window(date(2026, 10, 26))[0], day_window(DAY)[1])]

def test_fill_from_an_earlier_day_in_the_lookback_is_not_matched(conn, alerts, notes):
    """Match only the audited day's fills; an earlier day's fill pulled by the lookback isn't missing"""
    earlier = fill("alpaca-old", 5, Decimal("9.00"), "exec-old", at="2026-10-30T15:00:00Z")

    audit(conn, FakeAuditBroker([fill_activity(earlier)]), alerts, notes, check_now=False)

    row, = audit_rows(conn)
    assert (row.status, row.fills_at_alpaca, row.missing_in_db) == ("pass", 0, 0)

def test_today_is_audited_only_from_the_audit_time(conn):
    """Leave today out until AUDIT_MINUTES_AFTER_CLOSE after the close, then include it"""
    close = datetime(2026, 11, 2, 21, tzinfo=timezone.utc)

    before = days_to_audit(conn, close + timedelta(minutes=14), CALENDAR)[0]
    after = days_to_audit(conn, close + timedelta(minutes=15), CALENDAR)[0]

    assert (before, after) == ([date(2026, 10, 30)], [DAY])

def test_audits_trades_notes_go_to_the_trades_channel(conn, alerts, notes):
    """Send the handler's "manual trade recorded" note to the trades channel of its holding type, and the audit's own
    alert to critical"""
    manual_buy = fill("dash-buy", 3, Decimal("7.00"), "exec-dash-buy", at=BUY_AT)

    audit(conn, FakeAuditBroker([fill_activity(manual_buy)], positions={"AAPL": 3}), alerts, notes)

    assert any("Manual trade recorded" in message for message in notes.sent)
    assert notes.routes == [("trades", "swing")]
    assert any("recorded 1 fill" in message for message in alerts.sent)

def test_re_audit_with_no_share_check_keeps_a_share_failure_open(conn, strategy_id, alerts, notes):
    """Keep a share mismatch open when the next run of that day didn't check shares"""
    add_bracket(conn, strategy_id)
    buy = buy_fill()
    stream(conn, buy)
    audit(conn, FakeAuditBroker([fill_activity(buy)]), alerts, notes)

    audit(conn, FakeAuditBroker([fill_activity(buy)]), alerts, notes, check_now=False)

    assert audit_rows(conn)[0].resolved_at is None

def test_re_audit_alerts_only_the_new_problem(conn, strategy_id, alerts, notes):
    """Alert a new problem found by a re-audit without repeating the one already open"""
    buy, _ = round_trip(conn, strategy_id)
    audit(conn, FakeAuditBroker([fill_activity(buy)]), alerts, notes)

    audit(conn, FakeAuditBroker([fill_activity(buy, price="5.01")]), alerts, notes)

    assert len(alerts.sent) == 2
    assert "price_mismatch" in alerts.sent[1] and "missing_at_alpaca" not in alerts.sent[1]

def test_batch_after_the_close_checks_shares_and_cash_on_the_last_day_only(conn, strategy_id, alerts, notes):
    """Check shares and cash once, on the newest day of a catch-up batch"""
    add_bracket(conn, strategy_id)
    buy = buy_fill(at="2026-10-30T15:00:00Z")
    stream(conn, buy)

    catch_up_audits(conn, FakeAuditBroker([fill_activity(buy)], positions={"AAPL": 10}), AFTER_CLOSE, CALENDAR,
                    AuditWatch(), alert=alerts, notify=notes)

    assert [(r.audit_date, r.share_mismatches, r.alpaca_cash is None) for r in audit_rows(conn)] == [
        (date(2026, 10, 30), None, True), (DAY, 0, False)]

def test_starting_cash_run_is_not_counted_twice_the_next_day(conn, strategy_id, alerts, notes):
    """Pass the day after the first cash check when nothing moved: its fills and fees are already in the start"""
    updates = round_trip(conn, strategy_id)
    audit(conn, FakeAuditBroker([fill_activity(u) for u in updates] + [dated_activity("FEE", "-0.02")],
                                cash="1001.98"), alerts, notes)

    report = audit(conn, FakeAuditBroker(cash="1001.98"), alerts, notes, audit_date=NEXT_DAY, now=NEXT_CLOSE)

    assert (report.status, audit_rows(conn)[-1].expected_cash) == ("pass", Decimal("1001.9800"))

def test_reminder_names_days_that_couldnt_be_audited(conn, alerts, notes):
    """Remind in market hours about a day whose newest run is not_run, even with no open failure"""
    audit(conn, FakeAuditBroker(error="down"), alerts, notes)
    reminders = Alerts()

    sent = audit_reminders(conn, MARKET_OPEN, CALENDAR, AuditWatch(), alert=reminders)

    assert sent is True and "2026-11-02" in reminders.sent[0] and "couldn't be audited" in reminders.sent[0]

OPTION = "AAPL261120C00150000"

def test_option_fill_is_an_untracked_symbol_failure_and_the_rest_is_audited(conn, strategy_id, alerts, notes):
    """Fail with a no-ticker failure for a fill whose symbol doesn't fit the ticker column (an option), never try to
    record it, leave its position out of the share check, and still audit the rest"""
    updates = round_trip(conn, strategy_id)
    option = {**fill_activity(updates[0], fill_id="exec-opt"), "symbol": OPTION}

    report = audit(conn, FakeAuditBroker([fill_activity(u) for u in updates] + [option], positions={OPTION: 1}),
                   alerts, notes)

    row, = audit_rows(conn)
    assert (report.status, row.fills_at_alpaca, row.share_mismatches) == ("fail", 2, 0)
    assert [tuple(r) for r in failure_rows(conn)] == [("untracked_symbol", None, "exec-opt")]
    assert conn.execute("SELECT COUNT(*) FROM broker_events WHERE execution_id = 'exec-opt'").fetchone()[0] == 0
    assert len(alerts.sent) == 1 and OPTION in alerts.sent[0] and "No buys are blocked" in alerts.sent[0]

@pytest.mark.parametrize("error", [pyodbc.DataError("22001", "String or binary data would be truncated"),
                                   RuntimeError("handler bug: truncated")])
def test_fill_that_cant_be_saved_leaves_the_others_recorded(conn, alerts, notes, monkeypatch, error):
    """Record the day's other missed fills when one can't be recorded (a data error or a bug); that one stays
    missing_in_db and its alert names it"""
    first = fill("dash-a", 3, Decimal("7.00"), "exec-a", at=BUY_AT)
    second = fill("dash-b", 2, Decimal("7.00"), "exec-b", at=SELL_AT)
    real = end_of_day.process_update
    def failing(conn, update, now, **kwargs):
        if update.execution_id == "exec-a":
            raise error
        return real(conn, update, now, **kwargs)
    monkeypatch.setattr(end_of_day, "process_update", failing)

    report = audit(conn, FakeAuditBroker([fill_activity(first), fill_activity(second)]), alerts, notes,
                   check_now=False)

    assert (report.status, report.audit_fills) == ("fail", 1)
    assert [tuple(r) for r in failure_rows(conn)] == [("missing_in_db", "AAPL", "exec-a")]
    assert any("exec-a" in message and "truncated" in message for message in alerts.sent)

def test_catch_up_goes_on_after_a_day_that_fails_unexpectedly(conn, strategy_id, alerts, notes, monkeypatch):
    """Audit the later days when one day's audit fails for a reason other than an outage"""
    add_bracket(conn, strategy_id)
    buy = buy_fill(at="2026-10-29T15:00:00Z")
    stream(conn, buy)
    real, calls = end_of_day.match_fills, []
    def first_broken(alpaca, database):
        calls.append(1)
        if len(calls) == 1:
            raise KeyError("symbol")
        return real(alpaca, database)
    monkeypatch.setattr(end_of_day, "match_fills", first_broken)

    reports = catch_up_audits(conn, FakeAuditBroker([fill_activity(buy)], positions={"AAPL": 10}), AFTER_CLOSE,
                              CALENDAR, AuditWatch(), alert=alerts, notify=notes)

    assert [(r.audit_date, r.status) for r in reports] == [
        (date(2026, 10, 29), "failed"), (date(2026, 10, 30), "pass"), (DAY, "pass")]

def test_catch_up_stops_when_the_database_connection_is_lost(conn, strategy_id, alerts, notes, monkeypatch):
    """Stop the batch at the first day whose save loses the database connection"""
    add_bracket(conn, strategy_id)
    stream(conn, buy_fill(at="2026-10-29T15:00:00Z"))
    monkeypatch.setattr(end_of_day, "insert_audit", broken_database)

    reports = catch_up_audits(conn, FakeAuditBroker(), AFTER_CLOSE, CALENDAR, AuditWatch(), alert=alerts, notify=notes)

    assert [(r.audit_date, r.status) for r in reports] == [(date(2026, 10, 29), "failed")]

@pytest.mark.parametrize("broken", [{"id": "20261030150000000::broken", "activity_type": "FILL"},
                                    {"id": "broken", "activity_type": "FILL",
                                     "transaction_time": "2026-10-30T15:00:00Z"},
                                    {"id": "broken", "activity_type": "FEE", "date": "2026-10-30",
                                     "net_amount": "garbled"}])
def test_unreadable_activity_fails_only_its_own_day(conn, alerts, notes, broken):
    """Attach an activity that can't be read to the day its time, date or ID names, not to every day of the
    lookback"""
    own_day = audit(conn, FakeAuditBroker([broken]), alerts, notes, audit_date=date(2026, 10, 30), check_now=False)
    later_day = audit(conn, FakeAuditBroker([broken]), alerts, notes, check_now=False)

    assert (own_day.status, later_day.status) == ("fail", "pass")
    assert len(alerts.sent) == 1

def test_undatable_unreadable_activity_alerts_once(conn, alerts, notes):
    """Alert an unreadable activity with no readable date once, though each audited day lists it"""
    broken = {"id": "broken", "activity_type": "FILL"}

    audit(conn, FakeAuditBroker([broken]), alerts, notes, audit_date=date(2026, 10, 30), check_now=False)
    audit(conn, FakeAuditBroker([broken]), alerts, notes, check_now=False)

    assert len(alerts.sent) == 1

def test_re_audit_that_couldnt_read_an_activity_keeps_the_older_block(conn, strategy_id, alerts, notes, monkeypatch):
    """Keep a missing_in_db block when the re-audit of that day couldn't read an activity: the missing fill may be
    the one it couldn't read"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    real = end_of_day.process_update
    monkeypatch.setattr(end_of_day, "process_update",
                        lambda *args, **kwargs: HandleResult("failed", [("critical", "Couldn't handle a fill", None)]))
    audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target)], positions={"AAPL": 0}), alerts, notes)
    monkeypatch.setattr(end_of_day, "process_update", real)
    unreadable_target = {"id": fill_activity(target)["id"], "activity_type": "FILL"}

    audit(conn, FakeAuditBroker([fill_activity(buy), unreadable_target], positions={"AAPL": 0}), alerts, notes)

    assert audit_rows(conn)[0].resolved_at is None
    assert get_open_failure_tickers(conn, exclude_kinds=end_of_day.NOT_BLOCKING_KINDS) == frozenset({"AAPL"})

def test_problem_gone_from_a_replacing_run_is_alerted_as_resolved(conn, strategy_id, alerts, notes):
    """Alert that a problem went away even when the re-audit still fails for another one"""
    buy, _ = round_trip(conn, strategy_id)
    audit(conn, FakeAuditBroker([fill_activity(buy, price="5.01")]), alerts, notes)

    audit(conn, FakeAuditBroker([fill_activity(buy)]), alerts, notes)

    assert len(alerts.sent) == 2
    assert "price_mismatch" in alerts.sent[1] and "resolved" in alerts.sent[1]
    assert "missing_at_alpaca" not in alerts.sent[1]

def test_now_checks_on_an_earlier_day_ask_for_activities_up_to_now(conn, alerts, notes):
    """Ask for activities up to now when cash is checked on an earlier day, so a fee posted after the day's end is in
    the expected cash as it is in Alpaca's"""
    broker = FakeAuditBroker()

    audit(conn, broker, alerts, notes, now=datetime(2026, 11, 3, 13, tzinfo=timezone.utc))

    assert broker.calls[0][2] == datetime(2026, 11, 3, 13)

def test_reminder_alerts_once_when_it_cant_check_and_once_when_it_can_again(conn, monkeypatch):
    """Roll back and alert once (not every cycle) when the reminder can't read, and once when it reads again"""
    real = end_of_day.get_open_audits
    monkeypatch.setattr(end_of_day, "get_open_audits", broken_database)
    reminders, watch = Alerts(), AuditWatch()

    audit_reminders(conn, MARKET_OPEN, CALENDAR, watch, alert=reminders)
    audit_reminders(conn, MARKET_OPEN + timedelta(minutes=1), CALENDAR, watch, alert=reminders)
    monkeypatch.setattr(end_of_day, "get_open_audits", real)
    audit_reminders(conn, MARKET_OPEN + timedelta(minutes=2), CALENDAR, watch, alert=reminders)

    assert len(reminders.sent) == 2 and "couldn't check" in reminders.sent[0] and "again" in reminders.sent[1]
    assert conn.rollbacks == 2

def test_reminder_never_raises_on_a_broken_calendar(conn):
    """Return False when the calendar itself can't be read"""
    broken_calendar = {MARKET_OPEN.date(): {}}
    reminders = Alerts()

    assert audit_reminders(conn, MARKET_OPEN, broken_calendar, AuditWatch(), alert=reminders) is False
    assert (conn.rollbacks, len(reminders.sent)) == (1, 1)

def test_reminder_names_trading_days_with_no_audit_row(conn, strategy_id):
    """Remind about a trading day since the first trade that has no audit row (its audit failed before saving)"""
    add_bracket(conn, strategy_id)
    stream(conn, buy_fill())
    reminders = Alerts()

    sent = audit_reminders(conn, MARKET_OPEN, CALENDAR, AuditWatch(), alert=reminders)

    assert sent is True and "2026-11-02" in reminders.sent[0]

def test_saved_but_unhandled_fill_is_recorded_from_its_own_event(conn, strategy_id, alerts, notes):
    """Record a fill the stream saved but never handled from its own saved event, so it keeps its order and
    strategy, without saving it again as an audit_fill"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    save_broker_event(conn, event_type=target.event_type, alpaca_order_id=target.alpaca_order_id,
                      client_order_id=target.client_order_id, execution_id=target.execution_id, ticker=target.ticker,
                      event_at=target.event_at, raw_json=target.raw_json)

    report = audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target)]), alerts, notes)

    assert (report.status, report.audit_fills) == ("pass", 1)
    assert [(p.status, p.exit_reason, p.strategy_id) for p in positions(conn)] == [
        ("closed", "take_profit", strategy_id)]
    assert conn.execute("SELECT COUNT(*) FROM broker_events WHERE event_type = 'audit_fill'").fetchone()[0] == 0

def test_fill_activity_missing_a_fill_field_is_an_unreadable_failure(conn, strategy_id, alerts, notes):
    """Fail a FILL activity that can't become a fill (no side) as unreadable_activity, never as a crash: it isn't
    saved to account_activities, so its failure keeps it whole; its trade then has no Alpaca fill to match"""
    updates = round_trip(conn, strategy_id)
    no_side = {key: value for key, value in fill_activity(updates[1]).items() if key != "side"}

    report = audit(conn, FakeAuditBroker([fill_activity(updates[0]), no_side]), alerts, notes)

    assert report.status == "fail"
    assert {row.kind for row in failure_rows(conn)} == {"unreadable_activity", "missing_at_alpaca"}
    details = conn.execute("SELECT details FROM audit_failures WHERE kind = 'unreadable_activity'").fetchone()[0]
    assert json.loads(json.loads(details)["activity"]) == no_side
    assert conn.execute("SELECT COUNT(*) FROM account_activities").fetchone()[0] == 1

@pytest.mark.parametrize("activity", [None, "not a dict"])
def test_activity_that_isnt_a_record_is_an_unreadable_failure(conn, alerts, notes, activity):
    """Fail an activity that isn't even a record as unreadable_activity instead of failing the whole run"""
    report = audit(conn, FakeAuditBroker([activity]), alerts, notes, check_now=False)

    assert report.status == "fail"
    assert [tuple(row) for row in failure_rows(conn)] == [("unreadable_activity", None, "not a record")]

def test_unexpected_error_before_anything_is_saved_says_so(conn, alerts, notes, monkeypatch):
    """Say nothing was saved when the run breaks before the activities are committed"""
    def broken(*args, **kwargs):
        raise RuntimeError("odd record")
    monkeypatch.setattr(end_of_day, "insert_activity", broken)

    audit(conn, FakeAuditBroker([dated_activity("FEE", "-0.02")]), alerts, notes)

    assert "Nothing was saved" in alerts.sent[0] and "were saved" not in alerts.sent[0]
    assert (conn.execute("SELECT COUNT(*) FROM account_activities").fetchone()[0], audit_rows(conn)) == (0, [])

def test_activities_of_a_past_day_without_the_now_checks_end_at_the_days_end(conn, alerts, notes):
    """Ask only up to the day's end when shares and cash aren't checked, so later activities stay out of that day"""
    broker = FakeAuditBroker()

    audit(conn, broker, alerts, notes, now=datetime(2026, 11, 3, 13, tzinfo=timezone.utc), check_now=False)

    assert broker.calls[0][2] == day_window(DAY)[1]

def test_lost_connection_while_recording_a_fill_saves_nothing_and_stops(conn, strategy_id, alerts, notes, monkeypatch):
    """Treat a lost connection while recording a fill as a database outage: no run saved, cause "database", one
    outage alert, not a per-fill alert"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    monkeypatch.setattr(end_of_day, "process_update", broken_database)

    report = audit(conn, FakeAuditBroker([fill_activity(buy), fill_activity(target)]), alerts, notes)

    assert (report.status, report.cause, audit_rows(conn)) == ("failed", "database", [])
    assert len(alerts.sent) == 1 and "couldn't save" in alerts.sent[0]

def test_unreadable_activity_failure_is_resolved_when_the_day_reads_cleanly(conn, alerts, notes):
    """Resolve an unreadable_activity run once a re-audit of that day reads every activity"""
    broken = {"id": "20261102151000000::broken", "activity_type": "FEE", "date": "2026-11-02", "net_amount": "bad"}
    failed = audit(conn, FakeAuditBroker([broken]), alerts, notes, check_now=False)

    report = audit(conn, FakeAuditBroker([{**broken, "net_amount": "-0.02"}]), alerts, notes, check_now=False)

    assert (report.status, report.resolved) == ("pass", (failed.audit_id,))
    assert "resolved" in alerts.sent[-1]

def test_activity_too_big_for_its_columns_is_unreadable_and_the_rest_is_audited(conn, strategy_id, alerts, notes):
    """Fail an activity whose type or amount doesn't fit its column as unreadable_activity, before any insert, so it
    can't stop the run"""
    updates = round_trip(conn, strategy_id)
    too_big = [dated_activity("DIVCGLTAXES", "-0.02", number=1), dated_activity("FEE", "1" + "0" * 16, number=2)]

    report = audit(conn, FakeAuditBroker([fill_activity(u) for u in updates] + too_big), alerts, notes)

    assert report.status == "fail"
    assert [row.kind for row in failure_rows(conn)] == ["unreadable_activity", "unreadable_activity"]
    assert conn.execute("SELECT COUNT(*) FROM account_activities").fetchone()[0] == 2

def test_cash_check_starts_from_the_newest_passing_run(conn, alerts, notes):
    """Measure cash from the newest run whose cash passed, so differences within the tolerance never add up"""
    seed_cash_baseline(conn)
    audit(conn, FakeAuditBroker(cash="1000.008"), alerts, notes)

    report = audit(conn, FakeAuditBroker(cash="1000.016"), alerts, notes, audit_date=NEXT_DAY, now=NEXT_CLOSE)

    assert (report.status, audit_rows(conn)[-1].expected_cash) == ("pass", Decimal("1000.0080"))

def test_adjustment_entered_before_the_starting_run_is_not_counted_again(conn, alerts, notes):
    """Leave out an adjustment entered before the starting run read Alpaca's cash: that cash already holds it,
    even when the adjustment is dated after the audited day"""
    as_admin(conn, "INSERT INTO cash_adjustments (amount, effective_date, reason, note) "
                   "VALUES (50, '2026-11-03', 'deposit', 'already in the cash')")
    audit(conn, FakeAuditBroker(cash="1050"), alerts, notes)

    report = audit(conn, FakeAuditBroker(cash="1050"), alerts, notes, audit_date=NEXT_DAY, now=NEXT_CLOSE)

    assert report.status == "pass"

def test_day_failing_on_its_data_alerts_once_across_catch_ups(conn, strategy_id, alerts, notes, monkeypatch):
    """Alert a day that fails on its data once, and never say the audit runs again while that day still fails"""
    add_bracket(conn, strategy_id)
    buy = buy_fill(at="2026-10-30T15:00:00Z")
    stream(conn, buy)
    real = end_of_day.insert_audit
    def failing_on_one_day(conn, **kwargs):
        if kwargs["audit_date"] == date(2026, 10, 30):
            raise pyodbc.ProgrammingError("42000", "String or binary data would be truncated")
        return real(conn, **kwargs)
    monkeypatch.setattr(end_of_day, "insert_audit", failing_on_one_day)
    watch, broker = AuditWatch(), FakeAuditBroker([fill_activity(buy)], positions={"AAPL": 10})

    for _ in range(2):
        catch_up_audits(conn, broker, AFTER_CLOSE, CALENDAR, watch, alert=alerts, notify=notes)

    assert sum("couldn't save" in message for message in alerts.sent) == 1
    assert not any("running again" in message for message in alerts.sent)

def unhandled(*args, **kwargs):
    """Stand in for process_update and fail to handle the fill, with the handler's alert"""
    return HandleResult("failed", [("critical", "Couldn't handle", None)])

@pytest.mark.parametrize("failing", [unhandled, broken_match])
def test_fill_that_stays_unrecorded_alerts_once_across_re_audits(conn, strategy_id, alerts, notes, monkeypatch,
                                                                 failing):
    """Alert a missed fill the audit can't record once; re-audits of that day log it instead of alerting again"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    monkeypatch.setattr(end_of_day, "process_update", failing)
    broker = FakeAuditBroker([fill_activity(buy), fill_activity(target)])

    for _ in range(3):
        audit(conn, broker, alerts, notes, check_now=False)

    assert sum("exec-leg" in message or "Couldn't handle" in message for message in alerts.sent) == 2
    assert sum("Couldn't handle" in message or "couldn't record" in message for message in alerts.sent) == 1

def test_re_audit_without_the_share_check_lifts_a_fixed_tickers_block(conn, strategy_id, alerts, notes, monkeypatch):
    """Unblock a ticker whose fill problem a re-audit of that day found gone, though the re-audit didn't check shares:
    the old run's share failures move to the re-audit's run (marked as carried) and the old run is resolved"""
    add_bracket(conn, strategy_id)
    buy, target = buy_fill(), leg_fill()
    stream(conn, buy)
    real = end_of_day.process_update
    monkeypatch.setattr(end_of_day, "process_update", unhandled)
    broker = FakeAuditBroker([fill_activity(buy), fill_activity(target)], positions={"MSFT": 5})
    first = audit(conn, broker, alerts, notes)
    monkeypatch.setattr(end_of_day, "process_update", real)

    report = audit(conn, broker, alerts, notes, check_now=False)

    assert (report.status, report.resolved) == ("fail", ())
    assert audit_rows(conn)[0].resolved_at is not None and len(open_runs(conn)) == 1
    assert get_open_failure_tickers(conn, exclude_kinds=end_of_day.NOT_BLOCKING_KINDS) == frozenset()
    carried = conn.execute("SELECT ticker, details FROM audit_failures WHERE audit_id = ? ORDER BY ticker",
                           report.audit_id).fetchall()
    assert [(row.ticker, json.loads(row.details)) for row in carried] == [
        ("AAPL", {"carried_from": first.audit_id}), ("MSFT", {"carried_from": first.audit_id})]
    assert "missing_in_db on AAPL fill exec-leg" in alerts.sent[-1] and "resolved" in alerts.sent[-1]

def test_option_the_stream_kept_raw_is_one_untracked_failure_and_never_recorded(conn, alerts, notes):
    """Audit a day whose option fill the stream already kept raw: one untracked_symbol failure, no audit_fill, no
    second raw row"""
    option = fill("alpaca-opt-1", 1, Decimal("1.25"), "exec-opt", quantity=1, ticker=OPTION, at=BUY_AT)
    stream(conn, option)

    audit(conn, FakeAuditBroker([fill_activity(option)]), alerts, notes, check_now=False)

    assert [tuple(r) for r in failure_rows(conn)] == [("untracked_symbol", None, "exec-opt")]
    assert [row.event_type for row in conn.execute("SELECT event_type FROM broker_events")] == ["untracked_fill"]
