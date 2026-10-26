"""
test_risk_contract.py
Contract tests for risk's front door: they import only from the risk package and call only decide()

Any future redesign of risk (new sizers, model providers, a different rule engine) must pass these unchanged.
"""

#Standard Library
from datetime import datetime, timezone

#Third Party Libraries
import pytest

#Local Imports
from risk import BrokerPosition, OpenPosition, RecentExit, RiskContext, RiskRequest, StrategyState, decide
from strategies.signals import Signal

LIVE = 3
"""Strategy id of a live strategy with a $250 budget"""

SHADOW = 4
"""Strategy id of a shadow strategy"""

OFF = 5
"""Strategy id of a strategy switched off"""

UTC_NOW = datetime(2026, 10, 27, 14, 15, tzinfo=timezone.utc)
"""A fixed UTC time so no test depends on the clock"""

def _request(side="buy", strategy_id=LIVE, ticker="AAPL", price=10.0, holding_type="day"):
    """Build a request; buys at $10 size to $250 x 0.20 / $10 = 5 shares"""
    signal = Signal(side=side, time_frame="15Min", holding_type=holding_type, stop_price=None, target_price=None,
                    reason="test", strategy_version="1.0.0", ticker=ticker, features={})
    return RiskRequest(signal=signal, strategy_id=strategy_id, price=price)

def _context(positions=(), exits=(), broker=(), equity=1000.0, buying_power=1000.0):
    """Build a $1,000 account with one strategy in each mode"""
    strategies = (
        StrategyState(strategy_id=LIVE, mode="live", effective_budget=250.0),
        StrategyState(strategy_id=SHADOW, mode="shadow", effective_budget=0.0),
        StrategyState(strategy_id=OFF, mode="off", effective_budget=250.0),
    )
    return RiskContext(as_of=UTC_NOW, equity=equity, buying_power=buying_power, strategies=strategies,
                       open_positions=tuple(positions), recent_exits=tuple(exits), broker_positions=tuple(broker))

def _held(strategy_id, ticker, shares, price, position_id=1):
    """Build one open position"""
    return OpenPosition(position_id=position_id, strategy_id=strategy_id, ticker=ticker, holding_type="day",
                        shares_held=shares, avg_entry_price=price)

def test_healthy_buy_is_approved_at_sized_quantity():
    """Approve a live buy with room everywhere at the sizer's full quantity"""

    decision = decide(_request(), _context())

    assert decision.approved_quantity == 5
    assert decision.skip_reason is None
    assert decision.failed_checks == ()

def test_buy_records_sizer_and_version():
    """Record which sizer and version decided the size"""

    decision = decide(_request(), _context())

    assert decision.sizer == "fixed_budget:1.0.0"

def test_buy_returns_parameters_used():
    """Return the parameters the sizer used so they can be saved for evaluation"""

    decision = decide(_request(), _context())

    assert [p.name for p in decision.parameters] == ["position_fraction"]

def test_shadow_buy_is_skipped_but_keeps_its_size():
    """Skip a shadow buy, but keep the size it would have traded for simulated results"""

    decision = decide(_request(strategy_id=SHADOW), _context())

    assert decision.approved_quantity == 0
    assert decision.skip_reason == "shadow"
    assert decision.sized_quantity == 5

def test_off_strategy_buy_is_skipped():
    """Skip a buy from a strategy switched off"""

    decision = decide(_request(strategy_id=OFF), _context())

    assert decision.skip_reason == "strategy_off"

def test_unaffordable_share_is_skipped():
    """Skip a buy when one share costs more than the $50 slice"""

    decision = decide(_request(price=70.0), _context())

    assert decision.approved_quantity == 0
    assert decision.failed_checks == ("zero_quantity",)

def test_every_failure_is_recorded_in_priority_order():
    """Record every failed guardrail, highest priority first, with the first as the skip reason"""
    positions = [_held(OFF, "TSLA", 1, 10.0, position_id=i) for i in range(10)]
    exits = [RecentExit(strategy_id=LIVE, ticker="AAPL", exit_reason="stop_loss",
                        closed_at=datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc))]

    decision = decide(_request(), _context(positions=positions, exits=exits))

    assert decision.failed_checks == ("max_positions", "cooldown")
    assert decision.skip_reason == "max_positions"

def test_leverage_outranks_budget():
    """Report max_leverage before budget_exhausted when both fail"""
    positions = [_held(LIVE, "TSLA", 1, 240.0, position_id=1), _held(OFF, "NVDA", 1, 720.0, position_id=2)]

    decision = decide(_request(), _context(positions=positions))

    assert decision.failed_checks == ("max_leverage", "budget_exhausted")

def test_shadow_outranks_every_other_failure():
    """Report shadow first even when the account is also full"""
    positions = [_held(OFF, "TSLA", 1, 10.0, position_id=i) for i in range(10)]

    decision = decide(_request(strategy_id=SHADOW), _context(positions=positions))

    assert decision.skip_reason == "shadow"
    assert "max_positions" in decision.failed_checks

def test_sell_is_approved_for_every_share_held():
    """Sell every share the strategy holds when Alpaca holds them too"""
    context = _context(positions=[_held(LIVE, "AAPL", 5, 10.0)], broker=[BrokerPosition(ticker="AAPL", shares=5)])

    decision = decide(_request(side="sell"), context)

    assert decision.approved_quantity == 5
    assert decision.sizer == "held_shares"

def test_sell_ignores_guardrails():
    """Sell from a strategy that's off in an account over its leverage limit: guardrails never trap a position"""
    positions = [_held(OFF, "AAPL", 5, 10.0, position_id=1), _held(LIVE, "TSLA", 1, 5000.0, position_id=2)]
    context = _context(positions=positions, broker=[BrokerPosition(ticker="AAPL", shares=5)])

    decision = decide(_request(side="sell", strategy_id=OFF), context)

    assert decision.approved_quantity == 5

def test_sell_is_capped_by_alpaca_shares():
    """Sell only what Alpaca holds when the database thinks there are more, so the bot never goes short"""
    context = _context(positions=[_held(LIVE, "AAPL", 10, 10.0)], broker=[BrokerPosition(ticker="AAPL", shares=6)])

    decision = decide(_request(side="sell"), context)

    assert decision.approved_quantity == 6
    assert decision.sized_quantity == 10

def test_sell_with_nothing_held_is_skipped():
    """Skip a sell when the strategy holds none of the ticker"""
    context = _context(broker=[BrokerPosition(ticker="AAPL", shares=5)])

    decision = decide(_request(side="sell"), context)

    assert decision.skip_reason == "nothing_to_sell"

def test_sell_when_alpaca_holds_none_is_skipped():
    """Skip a sell when the database says the strategy holds shares but Alpaca holds none"""
    context = _context(positions=[_held(LIVE, "AAPL", 5, 10.0)])

    decision = decide(_request(side="sell"), context)

    assert decision.approved_quantity == 0
    assert decision.skip_reason == "nothing_to_sell"

def test_shadow_sell_is_skipped():
    """Skip a shadow strategy's sell: it holds no real shares"""

    decision = decide(_request(side="sell", strategy_id=SHADOW), _context())

    assert decision.skip_reason == "shadow"

def test_same_inputs_give_same_decision():
    """Return the same Decision for the same request and snapshot, so backtests can replay any day"""
    request, context = _request(), _context()

    first = decide(request, context)
    second = decide(request, context)

    assert first == second

def test_unknown_side_raises():
    """Raise on a side other than buy or sell"""

    with pytest.raises(ValueError, match="Unknown side"):
        decide(_request(side="short"), _context())

def test_holding_type_without_rules_raises():
    """Raise on a buy whose holding type has no guardrail list yet"""

    with pytest.raises(ValueError, match="No guardrails for holding type"):
        decide(_request(holding_type="swing"), _context())
