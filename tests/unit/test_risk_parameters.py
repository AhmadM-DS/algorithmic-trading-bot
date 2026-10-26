"""
test_risk_parameters.py
Unit tests for keeping risk parameters inside their bounds
"""

#Standard Library
from datetime import datetime, timezone
import math

#Third Party Libraries
import pytest

#Local Imports
from config.constants import RISK_PARAMETERS
from risk.context import RiskContext
from risk.parameters import PROVIDERS, apply_bounds, get_parameter

CONTEXT = RiskContext(as_of=datetime(2026, 10, 27, 14, 15, tzinfo=timezone.utc), equity=1000.0, buying_power=1000.0,
                      strategies=(), open_positions=(), recent_exits=(), broker_positions=())
"""An empty snapshot; the providers here don't read it"""

class HighProvider:
    """Fake model that always proposes 0.40, above position_fraction's max"""
    NAME = "high"
    VERSION = "2.1.0"

    def propose(self, name, strategy_id, context):
        return 0.40

class CrashingProvider:
    """Fake model that raises instead of proposing"""
    NAME = "crashing"
    VERSION = "1.0.0"

    def propose(self, name, strategy_id, context):
        raise RuntimeError("model file not found")

class ReturnsProvider:
    """Fake model that returns whatever value it was built with"""
    NAME = "returns"
    VERSION = "1.0.0"

    def __init__(self, value):
        self.value = value

    def propose(self, name, strategy_id, context):
        return self.value

def _switch_provider(monkeypatch, provider):
    """Make position_fraction use this provider for one test; monkeypatch undoes it afterwards"""
    monkeypatch.setitem(PROVIDERS, provider.NAME, provider)
    monkeypatch.setitem(RISK_PARAMETERS["position_fraction"], "provider", provider.NAME)

def test_value_inside_bounds_is_unchanged():
    """Leave a value alone when it's inside min / max and there's no history"""

    used, limited_by = apply_bounds("position_fraction", 0.10, None)

    assert used == pytest.approx(0.10)
    assert limited_by == ()

def test_value_above_max_is_clamped():
    """Pull a value above max down to max"""

    used, limited_by = apply_bounds("position_fraction", 0.40, None)

    assert used == pytest.approx(0.25)
    assert limited_by == ("clamp",)

def test_value_below_min_is_clamped():
    """Pull a value below min up to min"""

    used, limited_by = apply_bounds("position_fraction", 0.01, None)

    assert used == pytest.approx(0.05)
    assert limited_by == ("clamp",)

def test_rate_limit_caps_rise_from_previous():
    """Let a value rise at most max_daily_change above the previous value"""

    used, limited_by = apply_bounds("position_fraction", 0.25, 0.15)

    assert used == pytest.approx(0.20)
    assert limited_by == ("rate_limit",)

def test_rate_limit_caps_drop_from_previous():
    """Let a value fall at most max_daily_change below the previous value"""

    used, limited_by = apply_bounds("position_fraction", 0.05, 0.20)

    assert used == pytest.approx(0.15)
    assert limited_by == ("rate_limit",)

def test_change_within_rate_limit_is_unchanged():
    """Leave a value alone when it moved less than max_daily_change"""

    used, limited_by = apply_bounds("position_fraction", 0.18, 0.15)

    assert used == pytest.approx(0.18)
    assert limited_by == ()

def test_clamp_then_rate_limit():
    """Clamp first, then rate limit the clamped value, and record both"""

    used, limited_by = apply_bounds("position_fraction", 0.40, 0.15)

    assert used == pytest.approx(0.20)
    assert limited_by == ("clamp", "rate_limit")

def test_no_previous_skips_rate_limit():
    """Allow any value inside the bounds when there's no previous value"""

    used, limited_by = apply_bounds("position_fraction", 0.25, None)

    assert used == pytest.approx(0.25)
    assert limited_by == ()

def test_whole_number_parameter_is_clamped():
    """Clamp a cooldown counted in candles like any other parameter"""

    used, limited_by = apply_bounds("cooldown_stop_loss", 20, None)

    assert used == 8
    assert limited_by == ("clamp",)

def test_unknown_parameter_raises():
    """Raise when the parameter name isn't in RISK_PARAMETERS"""

    with pytest.raises(KeyError, match="position_fractoin"):
        apply_bounds("position_fractoin", 0.10, None)

def test_static_provider_returns_config_value():
    """Use the static value from RISK_PARAMETERS untouched"""

    value = get_parameter("position_fraction", 3, CONTEXT)

    assert value.proposed == pytest.approx(0.20)
    assert value.used == pytest.approx(0.20)
    assert value.limited_by == ()

def test_static_provider_is_labeled_with_version():
    """Record which provider and version produced the value"""

    value = get_parameter("position_fraction", 3, CONTEXT)

    assert value.provider == "static:1.0.0"

def test_static_provider_returns_whole_number_parameter():
    """Return a cooldown's static value in candles"""

    value = get_parameter("cooldown_stop_loss", 3, CONTEXT)

    assert value.used == 2

def test_model_proposal_is_clamped(monkeypatch):
    """Clamp a model's proposal and keep what it originally proposed"""
    _switch_provider(monkeypatch, HighProvider())

    value = get_parameter("position_fraction", 3, CONTEXT)

    assert value.proposed == pytest.approx(0.40)
    assert value.used == pytest.approx(0.25)
    assert value.limited_by == ("clamp",)

def test_model_proposal_is_rate_limited_from_previous(monkeypatch):
    """Clamp then rate limit a model's proposal when a previous value is given"""
    _switch_provider(monkeypatch, HighProvider())

    value = get_parameter("position_fraction", 3, CONTEXT, previous=0.15)

    assert value.used == pytest.approx(0.20)
    assert value.limited_by == ("clamp", "rate_limit")

def test_model_provider_is_labeled_with_version(monkeypatch):
    """Record the model's name and version, not static's"""
    _switch_provider(monkeypatch, HighProvider())

    value = get_parameter("position_fraction", 3, CONTEXT)

    assert value.provider == "high:2.1.0"

def test_crashing_provider_falls_back_to_static(monkeypatch):
    """Use the static value when the provider raises"""
    _switch_provider(monkeypatch, CrashingProvider())

    value = get_parameter("position_fraction", 3, CONTEXT)

    assert value.used == pytest.approx(0.20)
    assert value.limited_by == ("fallback",)

def test_crashing_provider_records_no_proposal(monkeypatch):
    """Record the proposal as NaN when the provider gave nothing usable"""
    _switch_provider(monkeypatch, CrashingProvider())

    value = get_parameter("position_fraction", 3, CONTEXT)

    assert math.isnan(value.proposed)

def test_crashing_provider_is_logged(monkeypatch, caplog):
    """Log a warning with the provider, the parameter and the error"""
    _switch_provider(monkeypatch, CrashingProvider())

    get_parameter("position_fraction", 3, CONTEXT)

    assert "crashing:1.0.0 failed on position_fraction" in caplog.text
    assert "model file not found" in caplog.text

@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), None, "0.2"])
def test_unusable_proposal_falls_back_to_static(monkeypatch, bad_value):
    """Use the static value when the provider returns something that isn't a finite number"""
    _switch_provider(monkeypatch, ReturnsProvider(bad_value))

    value = get_parameter("position_fraction", 3, CONTEXT)

    assert value.used == pytest.approx(0.20)
    assert value.limited_by == ("fallback",)

def test_switched_provider_is_restored_after_test():
    """Leave position_fraction on the static provider once a monkeypatched test ends"""

    value = get_parameter("position_fraction", 3, CONTEXT)

    assert RISK_PARAMETERS["position_fraction"]["provider"] == "static"
    assert value.provider == "static:1.0.0"
