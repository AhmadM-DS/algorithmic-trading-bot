"""
test_risk_guardrails.py
Unit tests for the buy guardrails
"""

#Standard Library
from datetime import datetime, timezone

#Local Imports
from risk.context import OpenPosition, RecentExit, RiskContext, StrategyState
from risk.decisions import RiskRequest
from risk.guardrails import (check_budget, check_buying_power, check_leverage, check_max_positions, check_mode,
                             check_cooldown, check_order_size, check_positions_per_ticker, check_quantity,
                             check_ticker_exposure)
from strategies.signals import Signal

LIVE = 3
"""Strategy id of a live strategy"""

SHADOW = 4
"""Strategy id of a shadow strategy"""

OFF = 5
"""Strategy id of a strategy switched off"""

UTC_NOW = datetime(2026, 10, 27, 14, 15, tzinfo=timezone.utc)
"""A fixed UTC time so no test depends on the clock"""

STRATEGIES = (
    StrategyState(strategy_id=LIVE, mode="live", effective_budget=250.0),
    StrategyState(strategy_id=SHADOW, mode="shadow", effective_budget=0.0),
    StrategyState(strategy_id=OFF, mode="off", effective_budget=250.0),
)
"""One strategy in each mode"""

def _buy(ticker="AAPL", strategy_id=LIVE, time_frame="15Min"):
    """Build a buy request for this ticker and strategy at $10"""
    signal = Signal(side="buy", time_frame=time_frame, holding_type="day", stop_price=None, target_price=None,
                    reason="test", strategy_version="1.0.0", ticker=ticker, features={})
    return RiskRequest(signal=signal, strategy_id=strategy_id, price=10.0)

def _context(positions=(), buying_power=1000.0, exits=()):
    """Build a snapshot holding these open positions"""
    return RiskContext(as_of=UTC_NOW, equity=1000.0, buying_power=buying_power, strategies=STRATEGIES,
                       open_positions=tuple(positions), recent_exits=tuple(exits), broker_positions=())

def _positions(count, strategy_id, ticker):
    """Build count open positions of one share each for one strategy and ticker"""
    return [OpenPosition(position_id=i, strategy_id=strategy_id, ticker=ticker, holding_type="day",
                         shares_held=1, avg_entry_price=10.0) for i in range(count)]

def test_live_strategy_passes_mode_check():
    """Let a live strategy buy"""

    reason = check_mode(_buy(), _context(), 5)

    assert reason is None

def test_shadow_strategy_is_blocked():
    """Block a shadow strategy's buy with "shadow" """

    reason = check_mode(_buy(strategy_id=SHADOW), _context(), 5)

    assert reason == "shadow"

def test_off_strategy_is_blocked():
    """Block an off strategy's buy with "strategy_off" """

    reason = check_mode(_buy(strategy_id=OFF), _context(), 5)

    assert reason == "strategy_off"

def test_zero_quantity_is_blocked():
    """Block a buy the sizer couldn't afford one share of"""

    reason = check_quantity(_buy(), _context(), 0)

    assert reason == "zero_quantity"

def test_one_share_passes_quantity_check():
    """Let a buy of at least one share through"""

    reason = check_quantity(_buy(), _context(), 1)

    assert reason is None

def test_account_below_max_positions_passes():
    """Let a buy through with 9 open positions and a limit of 10"""
    context = _context(_positions(9, LIVE, "AAPL"))

    reason = check_max_positions(_buy(), context, 5)

    assert reason is None

def test_account_at_max_positions_is_blocked():
    """Block a buy with 10 open positions, since it would make 11"""
    context = _context(_positions(10, LIVE, "AAPL"))

    reason = check_max_positions(_buy(), context, 5)

    assert reason == "max_positions"

def test_max_positions_counts_every_strategy():
    """Count other strategies' positions too: the limit is for the whole account"""
    context = _context(_positions(6, SHADOW, "TSLA") + _positions(4, OFF, "NVDA"))

    reason = check_max_positions(_buy(), context, 5)

    assert reason == "max_positions"

def test_one_position_in_ticker_can_stack():
    """Let a strategy add a second position in a ticker it holds once"""
    context = _context(_positions(1, LIVE, "AAPL"))

    reason = check_positions_per_ticker(_buy(), context, 5)

    assert reason is None

def test_two_positions_in_ticker_is_blocked():
    """Block a third position in the same ticker for the same strategy"""
    context = _context(_positions(2, LIVE, "AAPL"))

    reason = check_positions_per_ticker(_buy(), context, 5)

    assert reason == "max_positions_per_ticker"

def test_other_ticker_does_not_count_toward_ticker_limit():
    """Ignore the strategy's positions in other tickers"""
    context = _context(_positions(2, LIVE, "TSLA"))

    reason = check_positions_per_ticker(_buy(), context, 5)

    assert reason is None

def test_other_strategy_does_not_count_toward_ticker_limit():
    """Ignore other strategies' positions in the same ticker"""
    context = _context(_positions(2, OFF, "AAPL"))

    reason = check_positions_per_ticker(_buy(), context, 5)

    assert reason is None

def _held(strategy_id, ticker, dollars):
    """Build one open position that ties up this many dollars"""
    return OpenPosition(position_id=0, strategy_id=strategy_id, ticker=ticker, holding_type="day",
                        shares_held=1, avg_entry_price=dollars)

def test_order_at_max_order_size_passes():
    """Let an order of exactly 20% of equity through: 20 shares x $10 = $200 of $1,000"""

    reason = check_order_size(_buy(), _context(), 20)

    assert reason is None

def test_order_above_max_order_size_is_blocked():
    """Block an order above 20% of equity: 21 shares x $10 = $210"""

    reason = check_order_size(_buy(), _context(), 21)

    assert reason == "max_order_size"

def test_ticker_exposure_at_limit_passes():
    """Let a buy bring a ticker to exactly 15% of equity: $100 held + $50 = $150"""
    context = _context([_held(LIVE, "AAPL", 100.0)])

    reason = check_ticker_exposure(_buy(), context, 5)

    assert reason is None

def test_ticker_exposure_above_limit_is_blocked():
    """Block a buy that takes a ticker over 15% of equity: $110 held + $50 = $160"""
    context = _context([_held(LIVE, "AAPL", 110.0)])

    reason = check_ticker_exposure(_buy(), context, 5)

    assert reason == "max_per_ticker"

def test_ticker_exposure_counts_every_strategy():
    """Count another strategy's money in the same ticker: the limit is for the whole account"""
    context = _context([_held(OFF, "AAPL", 110.0)])

    reason = check_ticker_exposure(_buy(), context, 5)

    assert reason == "max_per_ticker"

def test_ticker_exposure_ignores_other_tickers():
    """Ignore money held in other tickers"""
    context = _context([_held(LIVE, "TSLA", 500.0)])

    reason = check_ticker_exposure(_buy(), context, 5)

    assert reason is None

def test_leverage_at_equity_passes():
    """Let a buy bring total exposure to exactly equity: $950 held + $50 = $1,000"""
    context = _context([_held(OFF, "TSLA", 950.0)])

    reason = check_leverage(_buy(), context, 5)

    assert reason is None

def test_leverage_above_equity_is_blocked():
    """Block a buy that would need borrowed money: $960 held + $50 = $1,010"""
    context = _context([_held(OFF, "TSLA", 960.0)])

    reason = check_leverage(_buy(), context, 5)

    assert reason == "max_leverage"

def test_order_within_buying_power_passes():
    """Let an order of exactly the buying power through"""
    context = _context(buying_power=50.0)

    reason = check_buying_power(_buy(), context, 5)

    assert reason is None

def test_order_above_buying_power_is_blocked():
    """Block an order bigger than Alpaca's buying power, even when equity is much larger"""
    context = _context(buying_power=40.0)

    reason = check_buying_power(_buy(), context, 5)

    assert reason == "buying_power"

def test_budget_at_limit_passes():
    """Let a buy fill the budget exactly: $200 held + $50 = $250"""
    context = _context([_held(LIVE, "TSLA", 200.0)])

    reason = check_budget(_buy(), context, 5)

    assert reason is None

def test_budget_above_limit_is_blocked():
    """Block a buy that goes over the budget: $210 held + $50 = $260"""
    context = _context([_held(LIVE, "TSLA", 210.0)])

    reason = check_budget(_buy(), context, 5)

    assert reason == "budget_exhausted"

def test_budget_ignores_other_strategies():
    """Count only this strategy's money against its budget"""
    context = _context([_held(OFF, "TSLA", 900.0)])

    reason = check_budget(_buy(), context, 5)

    assert reason is None

def test_shadow_budget_check_uses_shadow_budget(monkeypatch):
    """Check a shadow strategy against SHADOW_BUDGET, so its $0 real budget never adds a fake failure"""
    monkeypatch.setattr("risk.context.SHADOW_BUDGET", 250)

    reason = check_budget(_buy(strategy_id=SHADOW), _context(), 5)

    assert reason is None

def _exit(reason, hour, minute, strategy_id=LIVE, ticker="AAPL"):
    """Build an exit at this UTC time on the test day"""
    return RecentExit(strategy_id=strategy_id, ticker=ticker, exit_reason=reason,
                      closed_at=datetime(2026, 10, 27, hour, minute, tzinfo=timezone.utc))

def test_no_exit_passes_cooldown():
    """Let a buy through when the strategy hasn't exited the ticker today"""

    reason = check_cooldown(_buy(), _context(), 5)

    assert reason is None

def test_buy_inside_stop_loss_cooldown_is_blocked():
    """Block a buy 15 minutes after a stop-loss: 2 candles x 15 min = 30 min wait"""
    context = _context(exits=[_exit("stop_loss", 14, 0)])

    reason = check_cooldown(_buy(), context, 5)

    assert reason == "cooldown"

def test_buy_when_cooldown_ends_passes():
    """Let a buy through exactly 30 minutes after a stop-loss"""
    context = _context(exits=[_exit("stop_loss", 13, 45)])

    reason = check_cooldown(_buy(), context, 5)

    assert reason is None

def test_signal_exit_has_no_cooldown():
    """Let a buy through right after a signal exit, whose cooldown is 0"""
    context = _context(exits=[_exit("signal", 14, 10)])

    reason = check_cooldown(_buy(), context, 5)

    assert reason is None

def test_exit_without_cooldown_parameter_passes():
    """Let a buy through after an end-of-day exit, which has no cooldown parameter"""
    context = _context(exits=[_exit("end_of_day", 14, 10)])

    reason = check_cooldown(_buy(), context, 5)

    assert reason is None

def test_cooldown_scales_with_time_frame():
    """Wait 2 hours on a 1Hour strategy: a stop-loss at 13:00 still blocks at 14:15"""
    context = _context(exits=[_exit("stop_loss", 13, 0)])

    reason = check_cooldown(_buy(time_frame="1Hour"), context, 5)

    assert reason == "cooldown"

def test_newest_exit_decides_cooldown():
    """Use the most recent exit: a signal exit at 14:10 replaces a stop-loss at 14:05"""
    context = _context(exits=[_exit("stop_loss", 14, 5), _exit("signal", 14, 10)])

    reason = check_cooldown(_buy(), context, 5)

    assert reason is None

def test_other_ticker_exit_does_not_cool_down():
    """Ignore a stop-loss on a different ticker"""
    context = _context(exits=[_exit("stop_loss", 14, 0, ticker="TSLA")])

    reason = check_cooldown(_buy(), context, 5)

    assert reason is None

def test_other_strategy_exit_does_not_cool_down():
    """Ignore another strategy's stop-loss on the same ticker"""
    context = _context(exits=[_exit("stop_loss", 14, 0, strategy_id=OFF)])

    reason = check_cooldown(_buy(), context, 5)

    assert reason is None
