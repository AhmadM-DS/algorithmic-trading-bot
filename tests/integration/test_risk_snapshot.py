"""
test_risk_snapshot.py
Integration tests for risk/snapshot.py and risk/records.py: the snapshot, its halts and locks, and what risk writes
"""

#Standard Library
from datetime import timedelta

#Third Party Libraries
import pytest

#Local Imports
from fill_samples import CommitCounter
from risk import RiskRequest, RiskStateUnavailable, build_context, decide, record_risk_events, save_risk_decision
from risk_samples import (FakeBroker, add_event, add_strategy, add_used_parameter, as_admin, aware, closed_position,
                          db_now, events, open_position, add_signal)
from strategies.signals import Signal

class AlertRecorder:
    """Stands in for Discord: keeps each alert with how many commits had happened when it was sent"""

    def __init__(self, conn):
        self.conn = conn
        self.sent = []

    def channels(self):
        return {"critical": lambda message: self.sent.append(("critical", message, self.conn.commits)),
                "trades": lambda message: self.sent.append(("trades", message, self.conn.commits))}

@pytest.fixture
def conn(bot_conn):
    return CommitCounter(bot_conn)

def build(conn, broker=None, trading_mode="PAPER"):
    """Build the snapshot at the database's now"""
    return build_context(conn, broker or FakeBroker(), aware(db_now(conn)), trading_mode)

def state(context, strategy_id):
    return context.strategy(strategy_id)

def event_types(context):
    return [event.event_type for event in context.events]

def move_budget_set_at(conn, strategy_id, days):
    """Pretend the budget was set days ago, so earlier closes count toward the drawdown"""
    as_admin(conn, "UPDATE strategies SET budget_set_at = DATEADD(DAY, ?, budget_set_at) WHERE strategy_id = ?",
             (-days, strategy_id))

def buy(strategy_id, ticker="AAPL", price=10.0):
    signal = Signal(side="buy", time_frame="15Min", holding_type="day", stop_price=None, target_price=None,
                    reason="test", strategy_version="1.0.0", ticker=ticker, features={})
    return RiskRequest(signal=signal, strategy_id=strategy_id, price=price)

def test_paper_equity_is_capped(conn):
    """Use $1,000 of the $18,345.99 paper account, so paper behaves like the small live account"""

    context = build(conn, FakeBroker(equity="18345.99", last_equity="18345.99"))

    assert (context.equity, context.start_equity) == (1000.0, 1000.0)

def test_live_equity_is_not_capped(conn):
    """Use the whole live account (no cap)"""

    context = build(conn, FakeBroker(equity="540", last_equity="500"), trading_mode="LIVE")

    assert (context.equity, context.start_equity, context.account_daily_change) == (540.0, 500.0, 40.0)

def test_kill_switch_trips_at_five_percent_of_capped_start(conn):
    """Turn the kill switch on at a $51 loss on $1,000 (limit $50) with one critical event"""

    context = build(conn, FakeBroker(equity="949", last_equity="1000"))

    assert context.kill_switch is True
    assert [(e.event_type, e.channel) for e in context.events] == [("kill_switch", "critical")]

def test_kill_switch_stays_off_below_the_limit(conn):
    """Keep buying at a $49 loss"""

    context = build(conn, FakeBroker(equity="951", last_equity="1000"))

    assert (context.kill_switch, context.events) == (False, ())

def test_kill_switch_stays_on_after_the_account_recovers(conn):
    """Keep the kill switch on today once its row exists, even with the account back to even, and alert nothing new"""
    add_event(conn, "kill_switch")

    context = build(conn, FakeBroker(equity="1000", last_equity="1000"))

    assert (context.kill_switch, context.events) == (True, ())

def test_yesterdays_kill_switch_resets(conn):
    """Start a new day with the kill switch off"""
    add_event(conn, "kill_switch", occurred_at=db_now(conn) - timedelta(days=1))

    context = build(conn)

    assert context.kill_switch is False

def test_daily_halt_trips_at_three_percent_loss(conn):
    """Halt day buys at -$7.50 today on a $250 budget, with one trades-channel event"""
    strategy_id = add_strategy(conn)
    closed_position(conn, strategy_id, -7.5, db_now(conn))

    context = build(conn)

    assert state(context, strategy_id).halted_holding_types == frozenset({"day"})
    assert [(e.event_type, e.channel) for e in context.events] == [("daily_halt_day", "trades")]

def test_daily_halt_stays_off_above_the_loss_limit(conn):
    """Keep trading at -$7 today"""
    strategy_id = add_strategy(conn)
    closed_position(conn, strategy_id, -7, db_now(conn))

    context = build(conn)

    assert state(context, strategy_id).halted_holding_types == frozenset()

def test_daily_halt_trips_at_ten_percent_profit(conn):
    """Halt day buys at +$25 today on a $250 budget"""
    strategy_id = add_strategy(conn)
    closed_position(conn, strategy_id, 25, db_now(conn))

    context = build(conn)

    assert state(context, strategy_id).halted_holding_types == frozenset({"day"})

def test_daily_halt_stays_on_after_a_winning_close(conn):
    """Keep the halt for today once its row exists, even after a win brings the day back to even"""
    strategy_id = add_strategy(conn)
    add_event(conn, "daily_halt_day", strategy_id)
    closed_position(conn, strategy_id, -7.5, db_now(conn))
    closed_position(conn, strategy_id, 7.5, db_now(conn))

    context = build(conn)

    assert (state(context, strategy_id).halted_holding_types, context.events) == (frozenset({"day"}), ())

def test_drawdown_limit_pauses_at_five_percent_below_the_peak(conn):
    """Pause after +$10 then -$12.50: $12.50 below the peak is 5% of $250, with a critical event"""
    strategy_id = add_strategy(conn)
    move_budget_set_at(conn, strategy_id, 3)
    now = db_now(conn)
    closed_position(conn, strategy_id, 10, now - timedelta(days=2))
    closed_position(conn, strategy_id, -12.5, now - timedelta(days=1))

    context = build(conn)

    assert (state(context, strategy_id).drawdown, state(context, strategy_id).drawdown_paused) == (12.5, True)
    assert [(e.event_type, e.channel) for e in context.events] == [("drawdown_limit", "critical")]

def test_drawdown_pause_survives_a_winning_close(conn):
    """Stay paused after the row even when a later win shrinks the drawdown, until the admin re-sets the budget"""
    strategy_id = add_strategy(conn)
    move_budget_set_at(conn, strategy_id, 3)
    now = db_now(conn)
    closed_position(conn, strategy_id, -12.5, now - timedelta(days=2))
    add_event(conn, "drawdown_limit", strategy_id, occurred_at=now - timedelta(days=2) + timedelta(minutes=1))
    closed_position(conn, strategy_id, 6, now - timedelta(days=1))

    context = build(conn)

    assert (state(context, strategy_id).drawdown_paused, context.events) == (True, ())

def test_budget_change_lifts_the_drawdown_pause(conn):
    """Trade again once the admin changes the budget after a drawdown pause"""
    strategy_id = add_strategy(conn)
    move_budget_set_at(conn, strategy_id, 3)
    now = db_now(conn)
    closed_position(conn, strategy_id, -12.5, now - timedelta(days=2))
    add_event(conn, "drawdown_limit", strategy_id, occurred_at=now - timedelta(days=2) + timedelta(minutes=1))

    as_admin(conn, "UPDATE strategies SET budget = 249 WHERE strategy_id = ?", strategy_id)

    assert state(build(conn), strategy_id).drawdown_paused is False

def test_losses_shrink_the_effective_budget(conn):
    """Use $230 of a $250 budget after losing $20 since it was set"""
    strategy_id = add_strategy(conn)
    move_budget_set_at(conn, strategy_id, 3)
    closed_position(conn, strategy_id, -20, db_now(conn) - timedelta(days=1))

    context = build(conn)

    assert state(context, strategy_id).effective_budget == 230.0

def test_profits_dont_grow_the_effective_budget(conn):
    """Keep a $250 budget at $250 after making $20"""
    strategy_id = add_strategy(conn)
    move_budget_set_at(conn, strategy_id, 3)
    closed_position(conn, strategy_id, 20, db_now(conn) - timedelta(days=1))

    context = build(conn)

    assert state(context, strategy_id).effective_budget == 250.0

def test_live_budgets_scale_down_to_the_account(conn):
    """Scale $250 + $1,000 of live budgets to the $1,000 account (x 0.8) and alert once"""
    small, big = add_strategy(conn, "small", 250), add_strategy(conn, "big", 1000)

    context = build(conn)

    assert (context.scale_down, state(context, small).effective_budget) == (0.8, 200.0)
    assert [(e.event_type, e.channel) for e in context.events] == [("scale_down_started", "critical")]

def test_scale_down_stop_is_alerted_once(conn):
    """Send one "back to full size" event when the account covers the budgets again"""
    add_strategy(conn)
    add_event(conn, "scale_down_started")

    context = build(conn)

    assert event_types(context) == ["scale_down_stopped"]

def test_shadow_strategy_is_never_halted(conn):
    """Leave a shadow strategy with no halts or events, whatever it lost (it trades no real money)"""
    strategy_id = add_strategy(conn, mode="shadow", budget=0)
    closed_position(conn, strategy_id, -100, db_now(conn))

    context = build(conn)

    assert (state(context, strategy_id).halted_holding_types, context.events) == (frozenset(), ())

def test_budget_full_is_alerted_when_less_than_a_slot_is_left(conn):
    """Send budget_full with $210 of $250 in positions: $40 left is less than a $50 slot"""
    strategy_id = add_strategy(conn)
    open_position(conn, strategy_id, shares=21, price="10")

    context = build(conn)

    assert event_types(context) == ["budget_full"]

def test_budget_full_is_not_repeated(conn):
    """Send nothing while the newest row already says budget_full"""
    strategy_id = add_strategy(conn)
    open_position(conn, strategy_id, shares=21, price="10")
    add_event(conn, "budget_full", strategy_id)

    context = build(conn)

    assert context.events == ()

def test_budget_room_is_alerted_when_a_slot_fits_again(conn):
    """Send budget_room once the newest row says budget_full but a slot fits again"""
    strategy_id = add_strategy(conn)
    add_event(conn, "budget_full", strategy_id)

    context = build(conn)

    assert event_types(context) == ["budget_room"]

def test_previous_parameters_are_in_the_snapshot(conn):
    """Load yesterday's last value so the rate limit has something to compare with"""
    strategy_id = add_strategy(conn)
    add_used_parameter(conn, strategy_id, "position_fraction", 0.18, db_now(conn) - timedelta(days=1))

    context = build(conn)

    assert context.previous(strategy_id, "position_fraction") == 0.18

def test_broker_failure_raises_risk_state_unavailable(conn):
    """Raise RiskStateUnavailable when Alpaca doesn't answer, so the cycle skips buys"""

    with pytest.raises(RiskStateUnavailable, match="read timed out"):
        build(conn, FakeBroker(error=True))

def test_halted_buy_is_skipped_through_the_front_door(conn):
    """Skip a buy with daily_halt once the snapshot halts the strategy"""
    strategy_id = add_strategy(conn)
    closed_position(conn, strategy_id, -7.5, db_now(conn))

    decision = decide(buy(strategy_id), build(conn))

    assert decision.skip_reason == "daily_halt"

def test_kill_switch_outranks_the_daily_halt(conn):
    """Report kill_switch first when the account and the strategy both tripped"""
    strategy_id = add_strategy(conn)
    closed_position(conn, strategy_id, -7.5, db_now(conn))

    decision = decide(buy(strategy_id), build(conn, FakeBroker(equity="940", last_equity="1000")))

    assert decision.failed_checks[:2] == ("kill_switch", "daily_halt")

def test_record_saves_each_event_then_alerts_after_the_commit(conn):
    """Save the kill switch row, commit, then send its alert once"""
    recorder = AlertRecorder(conn)
    context = build(conn, FakeBroker(equity="940", last_equity="1000"))

    saved = record_risk_events(conn, context, recorder.channels())

    assert (saved, len(events(conn, "kill_switch"))) == (1, 1)
    assert [(channel, commits) for channel, _, commits in recorder.sent] == [("critical", 1)]

def test_recorded_event_locks_the_next_cycle(conn):
    """Find no new event on the next cycle once the row is saved, so the alert isn't repeated"""
    recorder = AlertRecorder(conn)
    record_risk_events(conn, build(conn, FakeBroker(equity="940", last_equity="1000")), recorder.channels())

    context = build(conn, FakeBroker(equity="940", last_equity="1000"))

    assert (context.kill_switch, context.events) == (True, ())

def test_record_with_no_events_writes_nothing(conn):
    """Commit nothing and alert nothing on a quiet cycle"""
    recorder = AlertRecorder(conn)

    saved = record_risk_events(conn, build(conn), recorder.channels())

    assert (saved, conn.commits, recorder.sent) == (0, 0, [])

def test_risk_decision_is_saved_with_the_snapshot(conn):
    """Save a decision's snapshot numbers, including the 008 columns"""
    strategy_id = add_strategy(conn)
    closed_position(conn, strategy_id, -4.5, db_now(conn) + timedelta(seconds=1))
    context = build(conn, FakeBroker(equity="990", last_equity="1000"))
    request = buy(strategy_id)

    decision_id = save_risk_decision(conn, add_signal(conn, strategy_id, db_now(conn)), request,
                                     decide(request, context), context)

    row = conn.execute("SELECT * FROM risk_decisions WHERE risk_decision_id = ?", decision_id).fetchone()
    assert (float(row.trading_budget), float(row.strategy_daily_pnl), float(row.account_daily_change),
            float(row.start_equity), row.sized_quantity) == (245.5, -4.5, -10.0, 1000.0, 4)

def test_risk_decision_saves_every_parameter_used(conn):
    """Save position_fraction, the drawdown limit and the cooldown after a stop-loss"""
    strategy_id = add_strategy(conn)
    closed_position(conn, strategy_id, -1, db_now(conn), exit_reason="stop_loss")
    context = build(conn)
    request = buy(strategy_id)

    decision_id = save_risk_decision(conn, add_signal(conn, strategy_id, db_now(conn)), request,
                                     decide(request, context), context)

    rows = conn.execute("SELECT [name], used FROM risk_decision_parameters WHERE risk_decision_id = ? ORDER BY [name]",
                        decision_id).fetchall()
    assert [(row.name, row.used) for row in rows] == \
           [("cooldown_stop_loss", 2.0), ("drawdown_limit", 0.05), ("position_fraction", 0.2)]
