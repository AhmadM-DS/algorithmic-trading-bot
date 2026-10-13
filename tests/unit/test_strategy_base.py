"""
test_strategy_base.py
Unit tests for the Strategy base class
"""

#Third Party Libraries
import pytest

#Local Imports
from strategies.base import Strategy

class CompleteStrategy(Strategy):
    """Fake strategy with every required setting"""
    NAME = "complete"
    TIME_FRAME = "15Min"
    CAPITAL_BUDGET = 15000
    DEFAULT_HOLDING_TYPE = "day"
    STOP_PERCENT_FROM_ENTRY = 0.02
    TARGET_PERCENT_FROM_ENTRY = 0.04
    LOOKBACK_WINDOW = 20
    VERSION = "1.1.05"

    def generate_signal(self, ticker, candles, position):
        return None

class IncompleteStrategy(Strategy):
    """Fake strategy missing NAME and VERSION"""
    NAME = None
    TIME_FRAME = "15Min"
    CAPITAL_BUDGET = 0
    DEFAULT_HOLDING_TYPE = "day"
    STOP_PERCENT_FROM_ENTRY = 0.02
    TARGET_PERCENT_FROM_ENTRY = 0.04
    LOOKBACK_WINDOW = 20
    VERSION = None

    def generate_signal(self, ticker, candles, position):
        return None

def test_complete_strategy_passes_check_settings():
    """Accept a strategy that sets every required setting"""
    strategy = CompleteStrategy()

    strategy.check_settings()

def test_incomplete_strategy_reports_every_missing_setting():
    """Raise one ValueError naming every missing setting, not just the first"""
    strategy = IncompleteStrategy()

    with pytest.raises(ValueError, match="IncompleteStrategy is missing required settings: NAME, VERSION"):
        strategy.check_settings()

def test_child_without_generate_signal_cannot_be_created():
    """Refuse to create a strategy that doesn't write generate_signal"""
    class NoSignalStrategy(Strategy):
        """Fake strategy without generate_signal"""

    with pytest.raises(TypeError, match="Can't instantiate abstract class NoSignalStrategy"):
        NoSignalStrategy()

def test_buy_sets_stop_below_and_target_above_entry():
    """Place a buy's stop 2% below and its target 4% above a whole-number entry"""
    strategy = CompleteStrategy()

    signal = strategy.make_signal(ticker="AAPL", side="buy", reason="test", entry_price=100, features={})

    assert signal.stop_price == pytest.approx(98)
    assert signal.target_price == pytest.approx(104)

def test_buy_prices_survive_floating_point_error():
    """Match the expected stop and target on an entry that floats can't store exactly"""
    strategy = CompleteStrategy()

    signal = strategy.make_signal(ticker="AAPL", side="buy", reason="test", entry_price=33.3, features={})

    assert signal.stop_price == pytest.approx(32.634)
    assert signal.target_price == pytest.approx(34.632)

def test_sell_has_no_stop_or_target():
    """Leave a sell's stop and target empty"""
    strategy = CompleteStrategy()

    signal = strategy.make_signal(ticker="AAPL", side="sell", reason="test", entry_price=100, features={})

    assert signal.stop_price is None
    assert signal.target_price is None

def test_unknown_side_raises_value_error():
    """Reject a side that isn't buy or sell"""
    strategy = CompleteStrategy()

    with pytest.raises(ValueError, match="Unknown side 'bleh'"):
        strategy.make_signal(ticker="AAPL", side="bleh", reason="test", entry_price=100, features={})
