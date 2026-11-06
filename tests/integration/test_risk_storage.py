"""
test_risk_storage.py
Integration tests for storage/risk.py: the reads behind the risk snapshot and saving risk decisions
"""

#Standard Library
from datetime import timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

#Local Imports
from risk_samples import (add_event, add_strategy, add_used_parameter, as_admin, closed_position, db_now,
                          open_position)
from storage.risk import (get_daily_pnl, get_events_since, get_events_since_budget_set, get_exits_since,
                          get_latest_events, get_open_positions, get_pnl_since_budget, get_previous_parameters,
                          get_strategy_rows)

NEW_YORK = ZoneInfo("America/New_York")

def new_york_date(value):
    return value.replace(tzinfo=timezone.utc).astimezone(NEW_YORK).date()

def test_pnl_since_budget_adds_closes_in_order_and_keeps_the_peak(bot_conn):
    """Total +10, -7.50, -3 to -0.50 and keep +10 as the peak (the example in the R2 decisions)"""
    strategy_id = add_strategy(bot_conn)
    start = db_now(bot_conn)
    for minutes, pnl in ((1, 10), (2, -7.5), (3, -3)):
        closed_position(bot_conn, strategy_id, pnl, start + timedelta(minutes=minutes))

    pnl = get_pnl_since_budget(bot_conn)[strategy_id]

    assert (pnl["total"], pnl["peak"]) == (Decimal("-0.5"), Decimal("10"))

def test_pnl_since_budget_ignores_positions_closed_before_the_budget_was_set(bot_conn):
    """Leave out a loss from before the budget was set, so a new budget starts clean"""
    strategy_id = add_strategy(bot_conn)
    start = db_now(bot_conn)
    closed_position(bot_conn, strategy_id, -20, start - timedelta(hours=1))
    closed_position(bot_conn, strategy_id, 5, start + timedelta(minutes=1))

    pnl = get_pnl_since_budget(bot_conn)[strategy_id]

    assert pnl["total"] == Decimal("5")

def test_budget_change_restarts_pnl_since_budget(bot_conn):
    """Count nothing once the admin changes the budget after the losses"""
    strategy_id = add_strategy(bot_conn)
    closed_position(bot_conn, strategy_id, -20, db_now(bot_conn))

    as_admin(bot_conn, "UPDATE strategies SET budget = 300 WHERE strategy_id = ?", strategy_id)

    assert strategy_id not in get_pnl_since_budget(bot_conn)

def test_daily_pnl_counts_only_today_per_holding_type(bot_conn):
    """Sum today's closes per holding type and leave yesterday's out"""
    strategy_id = add_strategy(bot_conn)
    now = db_now(bot_conn)
    closed_position(bot_conn, strategy_id, -4, now)
    closed_position(bot_conn, strategy_id, -1.5, now)
    closed_position(bot_conn, strategy_id, 3, now, holding_type="swing")
    closed_position(bot_conn, strategy_id, -50, now - timedelta(days=1))

    daily = get_daily_pnl(bot_conn, new_york_date(now))

    assert (daily[(strategy_id, "day")], daily[(strategy_id, "swing")]) == (Decimal("-5.5"), Decimal("3"))

def test_events_since_returns_todays_rows_only(bot_conn):
    """Find today's kill switch row and ignore yesterday's"""
    strategy_id = add_strategy(bot_conn)
    now = db_now(bot_conn)
    add_event(bot_conn, "kill_switch")
    add_event(bot_conn, "daily_halt_day", strategy_id, occurred_at=now - timedelta(days=1))

    found = get_events_since(bot_conn, ("kill_switch", "daily_halt_day"), now - timedelta(minutes=1))

    assert found == {("kill_switch", None)}

def test_drawdown_row_after_the_budget_was_set_pauses(bot_conn):
    """Count a drawdown row written after the budget was last set"""
    strategy_id = add_strategy(bot_conn)
    add_event(bot_conn, "drawdown_limit", strategy_id, occurred_at=db_now(bot_conn) + timedelta(seconds=1))

    paused = get_events_since_budget_set(bot_conn, "drawdown_limit")

    assert strategy_id in paused

def test_budget_change_lifts_the_drawdown_pause(bot_conn):
    """Stop counting the drawdown row once the admin changes the budget after it"""
    strategy_id = add_strategy(bot_conn)
    as_admin(bot_conn, "UPDATE strategies SET budget_set_at = DATEADD(HOUR, -1, budget_set_at) WHERE strategy_id = ?",
             strategy_id)
    add_event(bot_conn, "drawdown_limit", strategy_id, occurred_at=db_now(bot_conn) - timedelta(minutes=30))

    as_admin(bot_conn, "UPDATE strategies SET budget = 251 WHERE strategy_id = ?", strategy_id)

    assert strategy_id not in get_events_since_budget_set(bot_conn, "drawdown_limit")

def test_latest_events_returns_the_newest_per_strategy(bot_conn):
    """Return budget_room when it came after budget_full, per strategy, and None for account-wide rows"""
    first, second = add_strategy(bot_conn, "first"), add_strategy(bot_conn, "second")
    now = db_now(bot_conn)
    add_event(bot_conn, "budget_full", first, occurred_at=now - timedelta(minutes=2))
    add_event(bot_conn, "budget_room", first, occurred_at=now - timedelta(minutes=1))
    add_event(bot_conn, "budget_full", second, occurred_at=now - timedelta(minutes=1))
    add_event(bot_conn, "scale_down_started", occurred_at=now)

    latest = get_latest_events(bot_conn, ("budget_full", "budget_room"))
    scale = get_latest_events(bot_conn, ("scale_down_started", "scale_down_stopped"))

    assert (latest[first], latest[second], scale[None]) == ("budget_room", "budget_full", "scale_down_started")

def test_previous_parameters_are_the_last_used_before_today(bot_conn):
    """Return yesterday's last value, not an older one or one used today"""
    strategy_id = add_strategy(bot_conn)
    now = db_now(bot_conn)
    add_used_parameter(bot_conn, strategy_id, "position_fraction", 0.15, now - timedelta(days=2))
    add_used_parameter(bot_conn, strategy_id, "position_fraction", 0.18, now - timedelta(days=1))
    add_used_parameter(bot_conn, strategy_id, "position_fraction", 0.23, now)

    previous = get_previous_parameters(bot_conn, now - timedelta(hours=1))

    assert previous[(strategy_id, "position_fraction")] == 0.18

def test_open_positions_hold_their_shares(bot_conn):
    """Read an open position with its shares held and entry price"""
    strategy_id = add_strategy(bot_conn)
    position_id = open_position(bot_conn, strategy_id, shares=5, price="10")

    positions = [row for row in get_open_positions(bot_conn) if row["position_id"] == position_id]

    assert (positions[0]["ticker"], positions[0]["shares_held"], positions[0]["avg_entry_price"]) == \
           ("AAPL", 5, Decimal("10"))

def test_exits_since_returns_todays_closes_with_their_reason(bot_conn):
    """Return a stop-loss closed in the window and leave an older one out"""
    strategy_id = add_strategy(bot_conn)
    now = db_now(bot_conn)
    closed_position(bot_conn, strategy_id, -1, now, exit_reason="stop_loss")
    closed_position(bot_conn, strategy_id, -1, now - timedelta(days=1), exit_reason="stop_loss", ticker="TSLA")

    exits = [row for row in get_exits_since(bot_conn, now - timedelta(minutes=1)) if row["strategy_id"] == strategy_id]

    assert [(row["ticker"], row["exit_reason"]) for row in exits] == [("AAPL", "stop_loss")]

def test_strategy_rows_carry_budget_and_when_it_was_set(bot_conn):
    """Return each strategy's mode, budget and budget_set_at"""
    strategy_id = add_strategy(bot_conn, budget=250, mode="live")

    row = next(row for row in get_strategy_rows(bot_conn) if row["strategy_id"] == strategy_id)

    assert (row["mode"], row["budget"], row["budget_set_at"] is not None) == ("live", Decimal("250"), True)
