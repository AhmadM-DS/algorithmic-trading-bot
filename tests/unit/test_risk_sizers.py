"""
test_risk_sizers.py
Unit tests for the fixed_budget sizer
"""

#Standard Library
from datetime import datetime, timezone

#Third Party Libraries
import pytest

#Local Imports
from config.constants import RISK_PARAMETERS
from risk.context import RiskContext, StrategyState
from risk.decisions import RiskRequest
from risk.parameters import PROVIDERS
from risk.sizers import SIZERS, FixedBudgetSizer
from strategies.signals import Signal

LIVE = 3
"""Strategy id of a live strategy with a $250 effective budget"""

SHADOW = 4
"""Strategy id of a shadow strategy with a $0 budget"""

BUY_SIGNAL = Signal(side="buy", time_frame="15Min", holding_type="day", stop_price=None,
                    target_price=None, reason="test", strategy_version="1.0.0", ticker="AAPL", features={})
"""A day-trade buy; the sizer only reads the request's price and strategy"""

CONTEXT = RiskContext(
    as_of=datetime(2026, 10, 27, 14, 15, tzinfo=timezone.utc),
    equity=1000.0,
    buying_power=1000.0,
    strategies=(
        StrategyState(strategy_id=LIVE, mode="live", effective_budget=250.0),
        StrategyState(strategy_id=SHADOW, mode="shadow", effective_budget=0.0),
    ),
    open_positions=(),
    recent_exits=(),
    broker_positions=(),
)
"""One live and one shadow strategy"""

class HighProvider:
    """Fake model that always proposes 0.40, above position_fraction's max of 0.25"""
    NAME = "high"
    VERSION = "2.1.0"

    def propose(self, name, strategy_id, context):
        return 0.40

def _request(price, strategy_id=LIVE):
    """Build a buy request at this price"""
    return RiskRequest(signal=BUY_SIGNAL, strategy_id=strategy_id, price=price)

def test_live_strategy_sizes_from_effective_budget():
    """Buy position_fraction of the effective budget: $250 x 0.20 = $50 at $10 = 5 shares"""

    sizing = FixedBudgetSizer().size(_request(10.0), CONTEXT)

    assert sizing.quantity == 5

def test_shadow_strategy_sizes_from_shadow_budget(monkeypatch):
    """Size a shadow strategy from SHADOW_BUDGET even though its real budget is 0"""
    monkeypatch.setattr("risk.context.SHADOW_BUDGET", 500)

    sizing = FixedBudgetSizer().size(_request(10.0, strategy_id=SHADOW), CONTEXT)

    assert sizing.quantity == 10

def test_partial_share_is_dropped():
    """Round down to whole shares: $50 at $15 = 3.33 shares -> 3"""

    sizing = FixedBudgetSizer().size(_request(15.0), CONTEXT)

    assert sizing.quantity == 3

def test_float_error_does_not_lose_a_share(monkeypatch):
    """Buy 57 shares when the math is exactly 57, even though 0.57 x 100 is 56.999... in floating point"""
    monkeypatch.setitem(RISK_PARAMETERS["position_fraction"], "value", 0.57)
    monkeypatch.setitem(RISK_PARAMETERS["position_fraction"], "max", 1.0)
    context = RiskContext(as_of=CONTEXT.as_of, equity=1000.0, buying_power=1000.0,
                          strategies=(StrategyState(strategy_id=LIVE, mode="live", effective_budget=100.0),),
                          open_positions=(), recent_exits=(), broker_positions=())

    sizing = FixedBudgetSizer().size(_request(1.0), context)

    assert sizing.quantity == 57

def test_slice_too_small_for_one_share_is_zero():
    """Return 0 when one share costs more than the $50 slice"""

    sizing = FixedBudgetSizer().size(_request(70.0), CONTEXT)

    assert sizing.quantity == 0

def test_sizing_returns_position_fraction_used():
    """Return the position_fraction ParameterValue so decide() can log it"""

    sizing = FixedBudgetSizer().size(_request(10.0), CONTEXT)

    assert [p.name for p in sizing.parameters] == ["position_fraction"]
    assert sizing.parameters[0].used == pytest.approx(0.20)

def test_clamped_model_fraction_changes_size(monkeypatch):
    """Size with the clamped 0.25, not the model's 0.40: $250 x 0.25 = $62.50 at $10 = 6 shares"""
    monkeypatch.setitem(PROVIDERS, "high", HighProvider())
    monkeypatch.setitem(RISK_PARAMETERS["position_fraction"], "provider", "high")

    sizing = FixedBudgetSizer().size(_request(10.0), CONTEXT)

    assert sizing.quantity == 6
    assert sizing.parameters[0].limited_by == ("clamp",)

def test_unknown_strategy_raises():
    """Raise when the request's strategy isn't in the snapshot"""

    with pytest.raises(ValueError, match="isn't in this snapshot"):
        FixedBudgetSizer().size(_request(10.0, strategy_id=99), CONTEXT)

def test_sizer_is_registered_by_name():
    """Find the fixed_budget sizer under its NAME so POSITION_SIZER can pick it"""

    sizer = SIZERS["fixed_budget"]

    assert isinstance(sizer, FixedBudgetSizer)
