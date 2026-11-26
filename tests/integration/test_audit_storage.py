"""
test_audit_storage.py
Integration tests for storage/audit.py: saving activities and audit runs, and the reads the end-of-day audit makes
"""

#Standard Library
from datetime import date, datetime, timedelta
from decimal import Decimal

#Local Imports
from audit.matching import Failure, activity_record
from risk_samples import add_strategy, as_admin, db_now, ticker_id
from storage.audit import (count_audit_fills, count_catch_up_fills, get_cash_baseline, get_cash_movements,
                           get_database_shares,
                           get_dated_activities, get_first_activity_time, get_latest_audits, get_open_audits,
                           get_open_failure_keys,
                           get_open_failure_tickers, get_order_fill_mismatches, get_runs_after, get_saved_fill,
                           get_trades_between,
                           insert_activity, insert_audit, insert_failures, insert_not_run, resolve_audits)
from storage.fills import insert_position, insert_trade, save_broker_event
from storage.orders import insert_order

DAY = date(2026, 11, 24)
START, END = datetime(2026, 11, 24, 5), datetime(2026, 11, 25, 5)
IN_DAY = datetime(2026, 11, 24, 15)
COUNTS = {"fills_at_alpaca": 2, "fills_in_db": 2, "missing_in_db": 0, "missing_at_alpaca": 0, "catch_up_fills": 0,
          "audit_fills": 0, "price_mismatches": 0, "quantity_mismatches": 0, "share_mismatches": 0}

def fee(number=1, at="2026-11-24", amount="-0.02") -> dict:
    """Return a FEE activity as an account_activities record"""
    return activity_record({"id": f"20261124000000000::fee-{number}", "activity_type": "FEE", "date": at,
                            "net_amount": amount})

def add_order(conn, strategy_id, side="buy", number=1, ticker="ABC", filled=10) -> int:
    """Save a filled order of 10 shares and return its id"""
    order_id = insert_order(conn, client_order_id=f"coid-{side}-{number}", alpaca_order_id=f"alpaca-{side}-{number}",
                            side=side, quantity=10, order_type="market", time_in_force="day", submitted_at=IN_DAY,
                            status="filled", strategy_id=strategy_id, ticker_id=ticker_id(conn, ticker),
                            request_price=Decimal("5"), exit_reason="signal" if side == "sell" else None)
    conn.execute("UPDATE orders SET filled_quantity = ? WHERE order_id = ?", (filled, order_id))
    return order_id

def add_round_trip(conn, ticker="ABC", buy_price="5.00", sell_price="5.50", at=IN_DAY, sold=True) -> int:
    """Save a bought (and by default sold) position of 10 shares and return its position_id"""
    strategy_id = add_strategy(conn, name=f"s-{ticker}-{at:%H%M%S}")
    buy_id = add_order(conn, strategy_id, ticker=ticker, number=f"{ticker}{at:%H%M%S}")
    position_id = insert_position(conn, strategy_id=strategy_id, ticker_id=ticker_id(conn, ticker), signal_id=None,
                                  time_frame="15Min", holding_type="day", opened_at=at, quantity=10,
                                  price=Decimal(buy_price))
    insert_trade(conn, fill_id=f"buy-{ticker}-{at:%H%M%S}", side="buy", quantity=10, filled_at=at,
                 fill_price=Decimal(buy_price), time_frame="15Min", exit_reason=None, position_id=position_id,
                 order_id=buy_id)
    if sold:
        sell_id = add_order(conn, strategy_id, side="sell", ticker=ticker, number=f"{ticker}{at:%H%M%S}")
        insert_trade(conn, fill_id=f"sell-{ticker}-{at:%H%M%S}", side="sell", quantity=10,
                     filled_at=at + timedelta(minutes=5), fill_price=Decimal(sell_price), time_frame="15Min",
                     exit_reason="signal", position_id=position_id, order_id=sell_id)
    return position_id

def test_activity_is_saved_once(bot_conn):
    """Save a new activity and skip it quietly when it comes again (the lookback re-pulls days)"""

    first, second = insert_activity(bot_conn, fee()), insert_activity(bot_conn, fee())

    assert (first, second) == (True, False)
    assert bot_conn.execute("SELECT COUNT(*) FROM account_activities").fetchone()[0] == 1

def test_trades_between_returns_the_days_fills_with_their_ticker(bot_conn):
    """Return only the day's trades, with their ticker, oldest first"""
    add_round_trip(bot_conn)
    add_round_trip(bot_conn, ticker="XYZ", at=IN_DAY + timedelta(days=1))

    rows = get_trades_between(bot_conn, START, END)

    assert [(r["alpaca_fill_id"], r["ticker"], r["side"], r["quantity"], r["fill_price"]) for r in rows] == [
        ("buy-ABC-150000", "ABC", "buy", 10, Decimal("5.0000")),
        ("sell-ABC-150000", "ABC", "sell", 10, Decimal("5.5000"))]

def test_catch_up_fills_are_counted_for_the_day(bot_conn):
    """Count the fills the stream missed and the catch-up found that day"""
    for number, event_type in enumerate(("catch_up_fill", "catch_up_fill", "fill", "catch_up_status")):
        save_broker_event(bot_conn, event_type=event_type, alpaca_order_id="o", client_order_id=None,
                          execution_id=f"e{number}", ticker="ABC", event_at=IN_DAY, raw_json="{}")

    assert count_catch_up_fills(bot_conn, START, END) == 2

def test_order_fill_mismatches_cover_the_days_orders_only(bot_conn):
    """List an order of the day whose filled quantity isn't in its trades"""
    add_order(bot_conn, add_strategy(bot_conn), filled=10)

    rows = get_order_fill_mismatches(bot_conn, START, END)

    assert [(r["ticker"], r["filled_quantity"], r["quantity_in_trades"]) for r in rows] == [("ABC", 10, 0)]
    assert get_order_fill_mismatches(bot_conn, END, END + timedelta(days=1)) == []

def test_database_shares_sum_open_positions_per_ticker(bot_conn):
    """Add up open positions per ticker and leave out closed ones"""
    add_round_trip(bot_conn, sold=False)
    add_round_trip(bot_conn, at=IN_DAY + timedelta(hours=1), sold=False)
    add_round_trip(bot_conn, ticker="XYZ")

    assert get_database_shares(bot_conn) == {"ABC": 20}

def test_cash_baseline_is_the_newest_run_whose_cash_passed(bot_conn):
    """Use the newest run that read Alpaca's cash and found no cash failure as the starting point"""
    insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts={**COUNTS, "share_mismatches": None},
                 status="pass")
    insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="pass",
                 alpaca_cash=Decimal("1000"), expected_cash=Decimal("1000"))
    passed = insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail",
                          alpaca_cash=Decimal("990"), expected_cash=Decimal("990"))
    insert_failures(bot_conn, passed, [Failure("price_mismatch", "ABC")])
    cash_failed = insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail",
                               alpaca_cash=Decimal("980"), expected_cash=Decimal("990"))
    insert_failures(bot_conn, cash_failed, [Failure("cash", None)])

    baseline = get_cash_baseline(bot_conn)

    assert (baseline["audit_id"], baseline["alpaca_cash"], baseline["audit_date"]) == (passed, Decimal("990"), DAY)

def test_no_baseline_before_any_cash_check(bot_conn):
    """Return no starting point before any run checked cash"""
    assert get_cash_baseline(bot_conn) is None

def baseline_run(conn, run_at, audit_date=DAY) -> int:
    """Save a passing run that read Alpaca's cash at run_at and return its id"""
    return conn.execute("INSERT INTO audit_log (audit_date, audit_type, run_at, fills_at_alpaca, fills_in_db, "
                        "missing_in_db, missing_at_alpaca, [status], catch_up_fills, audit_fills, price_mismatches, "
                        "quantity_mismatches, share_mismatches, alpaca_cash, expected_cash) OUTPUT INSERTED.audit_id "
                        "VALUES (?, 'end_of_day', ?, 0, 0, 0, 0, 'pass', 0, 0, 0, 0, 0, 1000, 1000)",
                        (audit_date, run_at)).fetchone()[0]

def test_cash_movements_since_the_starting_run(bot_conn):
    """Sum fills (sells add, buys subtract), non-fill activities loaded after the starting run, and adjustments"""
    since = db_now(bot_conn) - timedelta(seconds=1)
    baseline = baseline_run(bot_conn, since)
    add_round_trip(bot_conn, at=since + timedelta(minutes=1))
    add_round_trip(bot_conn, ticker="OLD", at=since - timedelta(days=1))
    insert_activity(bot_conn, fee(amount="-0.02"))
    as_admin(bot_conn, "INSERT INTO cash_adjustments (amount, effective_date, reason) VALUES (100, '2026-11-24', "
                       "'deposit')")

    movements = get_cash_movements(bot_conn, baseline)

    assert movements == {"trades": Decimal("5.0000"), "activities": Decimal("-0.0200"),
                         "adjustments": Decimal("100.0000")}

def test_activity_saved_in_the_same_tick_as_the_starting_run_is_not_counted(bot_conn):
    """Leave out an activity whose loaded_at equals the starting run's run_at to the 100 ns, which Python can't hold"""
    insert_activity(bot_conn, fee(amount="-0.02"))
    loaded_at = bot_conn.execute("SELECT loaded_at FROM account_activities").fetchone()[0]
    baseline = baseline_run(bot_conn, loaded_at)
    as_admin(bot_conn, "UPDATE audit_log SET run_at = (SELECT loaded_at FROM account_activities) WHERE audit_id = ?",
             (baseline,))

    assert get_cash_movements(bot_conn, baseline)["activities"] == 0

def test_cash_movements_are_zero_when_nothing_moved(bot_conn):
    """Return zeros, not None, when nothing moved since the starting run"""

    movements = get_cash_movements(bot_conn, baseline_run(bot_conn, db_now(bot_conn)))

    assert movements == {"trades": 0, "activities": 0, "adjustments": 0}

def test_dated_activities_are_the_days_non_fills(bot_conn):
    """Return only the day's non-fill activities"""
    insert_activity(bot_conn, fee())
    insert_activity(bot_conn, fee(number=2, at="2026-11-25"))

    rows = get_dated_activities(bot_conn, START, END)

    assert [(r["activity_type"], r["net_amount"]) for r in rows] == [("FEE", Decimal("-0.0200"))]

def test_failed_run_and_its_failures_are_saved(bot_conn):
    """Save a failed run with one row per problem; the details are JSON"""
    audit_id = insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail",
                            notes="1 price mismatch")

    insert_failures(bot_conn, audit_id, [Failure("price_mismatch", "ABC", "f1", {"alpaca": {"price": "4.12"}}),
                                         Failure("cash", None, None, {"difference": "-5"})])

    rows = bot_conn.execute("SELECT kind, ticker, alpaca_fill_id, details FROM audit_failures WHERE audit_id = ? "
                            "ORDER BY audit_failure_id", audit_id).fetchall()
    assert [tuple(row) for row in rows] == [("price_mismatch", "ABC", "f1", '{"alpaca": {"price": "4.12"}}'),
                                            ("cash", None, None, '{"difference": "-5"}')]

def test_not_run_row_has_its_reason(bot_conn):
    """Save a not_run run with why it couldn't run"""
    audit_id = insert_not_run(bot_conn, DAY, "end_of_day", "Alpaca didn't answer: timed out")

    row = bot_conn.execute("SELECT [status], not_run_reason FROM audit_log WHERE audit_id = ?", audit_id).fetchone()
    assert tuple(row) == ("not_run", "Alpaca didn't answer: timed out")

def test_latest_audits_give_each_days_newest_run(bot_conn):
    """Read each day's newest run, so a re-audit replaces an older failure"""
    insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail")
    insert_audit(bot_conn, audit_date=DAY, audit_type="catch_up", counts=COUNTS, status="pass")
    insert_not_run(bot_conn, DAY + timedelta(days=1), "end_of_day", "down")

    latest = get_latest_audits(bot_conn)

    assert {day: row["status"] for day, row in latest.items()} == {DAY: "pass", DAY + timedelta(days=1): "not_run"}

def test_open_audits_and_later_runs_carry_their_failure_kinds(bot_conn):
    """Return open runs and later runs with the kinds of problem each found"""
    failed = insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail")
    insert_failures(bot_conn, failed, [Failure("price_mismatch", "ABC"), Failure("cash", None)])
    later = insert_audit(bot_conn, audit_date=DAY, audit_type="catch_up", counts={**COUNTS, "share_mismatches": None},
                         status="pass")

    open_runs = get_open_audits(bot_conn)
    runs = get_runs_after(bot_conn, open_runs[0]["audit_id"])

    assert [(r["audit_id"], r["audit_date"], r["kinds"]) for r in open_runs] == [
        (failed, DAY, {"price_mismatch", "cash"})]
    assert [(r["audit_id"], r["status"], r["share_mismatches"], r["alpaca_cash"], r["kinds"]) for r in runs] == [
        (later, "pass", None, None, set())]

def test_resolved_runs_leave_the_open_list(bot_conn):
    """Take a resolved run off the open list and stamp resolved_at"""
    failed = insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail")

    resolve_audits(bot_conn, [failed])

    assert get_open_audits(bot_conn) == []
    assert bot_conn.execute("SELECT resolved_at FROM audit_log WHERE audit_id = ?", failed).fetchone()[0] is not None

def test_open_failure_tickers_skip_resolved_runs_and_left_out_kinds(bot_conn):
    """Return the tickers of open failures, leaving out the kinds that don't block buys"""
    open_run = insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail")
    insert_failures(bot_conn, open_run, [Failure("price_mismatch", "ABC"), Failure("share_mismatch", "XYZ"),
                                         Failure("cash", None)])
    resolved = insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail")
    insert_failures(bot_conn, resolved, [Failure("missing_at_alpaca", "OLD")])
    resolve_audits(bot_conn, [resolved])

    assert get_open_failure_tickers(bot_conn, exclude_kinds=("cash", "share_mismatch")) == frozenset({"ABC"})

def test_first_activity_time_is_the_oldest_fill(bot_conn):
    """Return the oldest fill's time, where the catch-up starts"""
    add_round_trip(bot_conn, at=IN_DAY)
    add_round_trip(bot_conn, ticker="OLD", at=IN_DAY - timedelta(days=3))

    assert get_first_activity_time(bot_conn) == IN_DAY - timedelta(days=3)

def test_first_activity_time_counts_an_order_older_than_every_trade(bot_conn):
    """Start at the oldest order when it's older than every trade, so a first day whose fills were all missed is
    still audited"""
    add_round_trip(bot_conn, at=IN_DAY)
    insert_order(bot_conn, client_order_id="coid-first", alpaca_order_id="alpaca-first", side="buy", quantity=10,
                 order_type="market", time_in_force="day", submitted_at=IN_DAY - timedelta(days=5), status="filled",
                 strategy_id=add_strategy(bot_conn, name="first"), ticker_id=ticker_id(bot_conn, "ABC"),
                 request_price=Decimal("5"))

    assert get_first_activity_time(bot_conn) == IN_DAY - timedelta(days=5)

def test_first_activity_time_is_none_with_nothing_saved(bot_conn):
    """Return None when no fill, order or Alpaca event is saved yet"""
    assert get_first_activity_time(bot_conn) is None

def test_saved_fill_leaves_out_a_message_saved_unreadable(bot_conn):
    """Return the readable saved event of a fill, never the unreadable one saved with no Alpaca order id"""
    save_broker_event(bot_conn, event_type="fill", alpaca_order_id=None, client_order_id=None,
                      execution_id="exec-1", ticker=None, event_at=None, raw_json='{"event": "fill"}')
    unreadable_only = get_saved_fill(bot_conn, "exec-1")
    save_broker_event(bot_conn, event_type="catch_up_fill", alpaca_order_id="alpaca-1", client_order_id=None,
                      execution_id="exec-1", ticker="ABC", event_at=IN_DAY, raw_json='{"readable": true}')

    assert unreadable_only is None
    assert get_saved_fill(bot_conn, "exec-1") == {"event_type": "catch_up_fill", "raw_json": '{"readable": true}'}

def test_open_failure_keys_are_one_days_unresolved_problems(bot_conn):
    """Return (kind, ticker, fill_id) of a day's open failures, so a re-audit finding the same ones stays quiet"""
    open_run = insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail")
    insert_failures(bot_conn, open_run, [Failure("price_mismatch", "ABC", "f1"), Failure("cash", None)])
    other_day = insert_audit(bot_conn, audit_date=DAY + timedelta(days=1), audit_type="end_of_day", counts=COUNTS,
                             status="fail")
    insert_failures(bot_conn, other_day, [Failure("missing_at_alpaca", "XYZ", "f2")])

    assert get_open_failure_keys(bot_conn, DAY) == {("price_mismatch", "ABC", "f1"), ("cash", None, None)}

def test_open_failure_tickers_with_nothing_left_out_returns_every_ticker(bot_conn):
    """Return every open failure's ticker when no kinds are left out (an empty list must not hide them all)"""
    open_run = insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail")
    insert_failures(bot_conn, open_run, [Failure("price_mismatch", "ABC"), Failure("share_mismatch", "XYZ")])

    assert get_open_failure_tickers(bot_conn) == frozenset({"ABC", "XYZ"})

def test_open_failure_keys_include_account_kinds_from_any_day(bot_conn):
    """Count an open cash or share problem as known whatever day found it, other kinds only on their own day"""
    monday = insert_audit(bot_conn, audit_date=DAY, audit_type="end_of_day", counts=COUNTS, status="fail")
    insert_failures(bot_conn, monday, [Failure("cash", None), Failure("price_mismatch", "ABC", "f1")])

    keys = get_open_failure_keys(bot_conn, DAY + timedelta(days=1), any_day_kinds=("share_mismatch", "cash"))

    assert keys == {("cash", None, None)}

def test_adjustments_entered_before_the_starting_point_are_left_out(bot_conn):
    """Count only adjustments entered after the starting run read the cash, whatever date they carry; one entered
    before is already in that cash"""
    as_admin(bot_conn, "INSERT INTO cash_adjustments (amount, effective_date, reason, created_at) VALUES "
                       "(100, '2026-11-25', 'deposit', '2026-11-20 12:00'), "
                       "(5, '2026-11-01', 'fee', '2026-11-22 12:00')")

    movements = get_cash_movements(bot_conn, baseline_run(bot_conn, datetime(2026, 11, 21, 12), audit_date=DAY))

    assert movements["adjustments"] == Decimal("5.0000")

def test_audit_fills_count_only_fills_that_reached_trades(bot_conn):
    """Count an audit_fill event only once its fill is in trades: a recording that failed isn't a recorded fill"""
    add_round_trip(bot_conn, at=IN_DAY, sold=False)
    for execution_id in (f"buy-ABC-{IN_DAY:%H%M%S}", "never-recorded"):
        save_broker_event(bot_conn, event_type="audit_fill", alpaca_order_id="alpaca-1", client_order_id=None,
                          execution_id=execution_id, ticker="ABC", event_at=IN_DAY, raw_json="{}")

    assert count_audit_fills(bot_conn, START, END) == 1
