"""
test_risk_context.py
Unit tests for the RiskContext snapshot and its records
"""

#Standard Library
from datetime import datetime, timezone

#Third Party Libraries
import pytest

#Local Imports
from risk.context import BrokerPosition, OpenPosition, RecentExit, RiskContext, StrategyState

UTC_NOW = datetime(2026, 10, 27, 14, 15, tzinfo=timezone.utc)
"""A fixed UTC time so no test depends on the clock"""

MOMENTUM = 3
"""Strategy id of the sample momentum strategy"""

ICT = 4
"""Strategy id of the sample ICT strategy"""

CONTEXT = RiskContext(
    as_of=UTC_NOW,
    equity=1000.0,
    buying_power=1000.0,
    strategies=(
        StrategyState(strategy_id=MOMENTUM, mode="live", effective_budget=250.0),
        StrategyState(strategy_id=ICT, mode="shadow", effective_budget=250.0),
    ),
    open_positions=(
        OpenPosition(position_id=1, strategy_id=MOMENTUM, ticker="AAPL", holding_type="day", shares_held=2, avg_entry_price=200.0),
        OpenPosition(position_id=2, strategy_id=MOMENTUM, ticker="AAPL", holding_type="day", shares_held=1, avg_entry_price=210.0),
        OpenPosition(position_id=3, strategy_id=MOMENTUM, ticker="TSLA", holding_type="day", shares_held=1, avg_entry_price=250.0),
        OpenPosition(position_id=4, strategy_id=ICT, ticker="AAPL", holding_type="day", shares_held=3, avg_entry_price=199.0),
    ),
    recent_exits=(
        RecentExit(strategy_id=MOMENTUM, ticker="AAPL", exit_reason="stop_loss", closed_at=datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)),
        RecentExit(strategy_id=MOMENTUM, ticker="AAPL", exit_reason="signal", closed_at=datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)),
    ),
    broker_positions=(
        BrokerPosition(ticker="AAPL", shares=6),
        BrokerPosition(ticker="TSLA", shares=1),
    ),
)
"""Two strategies: momentum stacks two AAPL positions and holds TSLA, ICT holds AAPL"""

def test_strategy_state_rejects_unknown_mode():
    """Raise when the mode isn't off, shadow or live"""

    with pytest.raises(ValueError, match="Invalid mode"):
        StrategyState(strategy_id=1, mode="paused", effective_budget=15)

def test_strategy_state_rejects_negative_budget():
    """Raise when the effective budget is below 0"""

    with pytest.raises(ValueError, match="Invalid effective_budget"):
        StrategyState(strategy_id=2, mode="off", effective_budget=-3)

def test_live_trading_budget_is_effective_budget():
    """Trade a live strategy from its effective budget"""
    state = StrategyState(strategy_id=1, mode="live", effective_budget=180.0)

    budget = state.trading_budget

    assert budget == pytest.approx(180.0)

def test_shadow_trading_budget_is_shadow_budget(monkeypatch):
    """Trade a shadow strategy from SHADOW_BUDGET, not its $0 real budget"""
    monkeypatch.setattr("risk.context.SHADOW_BUDGET", 500)
    state = StrategyState(strategy_id=1, mode="shadow", effective_budget=0.0)

    budget = state.trading_budget

    assert budget == 500

def test_strategy_state_rejects_nan_budget():
    """Raise when the effective budget is NaN, which slips past a plain < 0 check"""

    with pytest.raises(ValueError, match="Invalid effective_budget"):
        StrategyState(strategy_id=2, mode="live", effective_budget=float("nan"))

def test_position_cost_is_shares_times_entry_price():
    """Calculate cost as shares held times the average entry price"""
    position = OpenPosition(position_id=1, strategy_id=3, ticker="AAPL", holding_type="day", shares_held=10, avg_entry_price=13.48)

    cost = position.cost

    assert cost == pytest.approx(134.80)

def test_context_rejects_naive_as_of():
    """Raise when as_of has no time zone"""

    with pytest.raises(ValueError, match="Invalid timezone"):
        RiskContext(as_of=datetime(2026, 10, 27, 14, 15), equity=15, buying_power=300, strategies=(), open_positions=(), recent_exits=(), broker_positions=())

def test_context_accepts_utc_as_of():
    """Accept an as_of time in UTC"""

    context = RiskContext(as_of=UTC_NOW, equity=15, buying_power=300, strategies=(), open_positions=(), recent_exits=(), broker_positions=())

    assert context.as_of == UTC_NOW

def test_strategy_returns_matching_state():
    """Return the state of the requested strategy"""

    state = CONTEXT.strategy(ICT)

    assert state.mode == "shadow"

def test_strategy_rejects_unknown_id():
    """Raise when the strategy isn't in the snapshot"""

    with pytest.raises(ValueError, match="isn't in this snapshot"):
        CONTEXT.strategy(99)

def test_positions_filters_by_strategy_and_ticker():
    """Return only the positions of that strategy in that ticker"""

    positions = CONTEXT.positions(MOMENTUM, "AAPL")

    assert [p.position_id for p in positions] == [1, 2]

def test_positions_filters_by_strategy_only():
    """Return every ticker's positions for one strategy"""

    positions = CONTEXT.positions(strategy_id=MOMENTUM)

    assert [p.position_id for p in positions] == [1, 2, 3]

def test_positions_with_no_filters_returns_all():
    """Return every open position when no filter is given"""

    positions = CONTEXT.positions()

    assert len(positions) == 4

def test_exposure_sums_ticker_across_strategies():
    """Add up the cost of every strategy's AAPL positions"""

    exposure = CONTEXT.exposure(ticker="AAPL")

    assert exposure == pytest.approx(2 * 200 + 210 + 3 * 199)

def test_exposure_sums_whole_account_without_filters():
    """Add up the cost of every open position when no filter is given"""

    exposure = CONTEXT.exposure()

    assert exposure == pytest.approx(2 * 200 + 210 + 250 + 3 * 199)

def test_exposure_is_zero_when_nothing_matches():
    """Return 0 for a ticker no strategy holds"""

    exposure = CONTEXT.exposure(ticker="NVDA")

    assert exposure == 0

def test_shares_held_sums_stacked_positions():
    """Add up shares across one strategy's stacked positions in a ticker"""

    shares = CONTEXT.shares_held(MOMENTUM, "AAPL")

    assert shares == 3

def test_shares_held_is_zero_for_unheld_ticker():
    """Return 0 when the strategy holds none of that ticker"""

    shares = CONTEXT.shares_held(ICT, "TSLA")

    assert shares == 0

def test_broker_shares_returns_alpaca_count():
    """Return what Alpaca holds for the whole account"""

    shares = CONTEXT.broker_shares("AAPL")

    assert shares == 6

def test_broker_shares_is_zero_for_unheld_ticker():
    """Return 0 when Alpaca holds none of that ticker"""

    shares = CONTEXT.broker_shares("NVDA")

    assert shares == 0

def test_last_exit_returns_newest():
    """Return the most recent exit when there are several"""

    last = CONTEXT.last_exit(MOMENTUM, "AAPL")

    assert last.closed_at == datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)

def test_last_exit_is_none_without_exits():
    """Return None when the strategy hasn't exited that ticker today"""

    last = CONTEXT.last_exit(ICT, "AAPL")

    assert last is None
