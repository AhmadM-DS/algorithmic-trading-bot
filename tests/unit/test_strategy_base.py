"""
test_strategy_base.py
Unit tests for the Strategy base class
"""

#Third Party Libraries
import pandas as pd
import pytest
from datetime import time

#Local Imports
from strategies.base import Strategy

class CompleteStrategy(Strategy):
    """Fake strategy with every required setting"""
    NAME = "complete"
    TIME_FRAME = "15Min"
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
    DEFAULT_HOLDING_TYPE = "day"
    STOP_PERCENT_FROM_ENTRY = 0.02
    TARGET_PERCENT_FROM_ENTRY = 0.04
    LOOKBACK_WINDOW = 20
    VERSION = None

    def generate_signal(self, ticker, candles, position):
        return None

class SwingStrategy(CompleteStrategy):
    """Fake strategy using swing as a holding type"""
    DEFAULT_HOLDING_TYPE = "swing"

class WrongTimeFrameStrategy(CompleteStrategy):
    """Fake strategy with a misspelled TIME_FRAME"""
    TIME_FRAME = "15MIN"

class UnderTimeFrameStrategy(CompleteStrategy):
    """Fake strategy with TIME_FRAME below the minimum"""
    TIME_FRAME = "1Min"

class MultipleProblemsStrategy(CompleteStrategy):
    """Fake strategy with multiple incorrectly defined class attributes"""
    DEFAULT_HOLDING_TYPE = "swing"
    TIME_FRAME = "1HOUR"

class ValidTradingWindowStrategy(CompleteStrategy):
    """Fake strategy with a valid trading window"""
    TRADING_WINDOW = (time(9, 45), time(14, 15))

class MarketTradingWindowStrategy(CompleteStrategy):
    """Fake strategy with a market hours trading window"""
    TRADING_WINDOW = (time(9, 30), time(16, 0))

class InvalidKindTradingWindowStrategy(CompleteStrategy):
    """Fake strategy with a valid trading window but invalid kind using session"""
    TRADING_WINDOW = (time(10, 0), time(15, 30))
    TIME_FRAME = "1Day"

class StartGreaterEndTradingWindowStrategy(CompleteStrategy):
    """Fake strategy with start time after end time"""
    TRADING_WINDOW = (time(10, 30), time(9, 45))

class BeforeOpenTradingWindowStrategy(CompleteStrategy):
    """Fake strategy with start time before market hour open"""
    TRADING_WINDOW = (time(6, 30), time(9, 45))

class AfterCloseTradingWindowStrategy(CompleteStrategy):
    """Fake strategy with close time after market hour close"""
    TRADING_WINDOW = (time(9, 30), time(17, 0))

class InvalidValueTradingWindowStrategy(CompleteStrategy):
    """Fake strategy with invalid string values for the TRADING_WINDOW"""
    TRADING_WINDOW = ("9:30", "16:00")

class ShortLookbackStrategy(CompleteStrategy):
    """Fake strategy whose lookback is shorter than RSI 14 needs"""
    INDICATORS = [("rsi", 14)]
    LOOKBACK_WINDOW = 20

class ExactLookbackStrategy(CompleteStrategy):
    """Fake strategy whose lookback is exactly what its largest indicator needs"""
    INDICATORS = [("ema", 9), ("rsi", 14)]
    LOOKBACK_WINDOW = 65

class LargestIndicatorStrategy(CompleteStrategy):
    """Fake strategy whose largest need is its second indicator"""
    INDICATORS = [("rsi", 14), ("ema", 200)]
    LOOKBACK_WINDOW = 100

class InvalidIndicatorStrategy(CompleteStrategy):
    """Fake strategy listing an indicator that has no window"""
    INDICATORS = [("vwap",)]

class NoOuterListStrategy(CompleteStrategy):
    """Fake strategy that forgot the brackets around its one indicator"""
    INDICATORS = ("rsi", 14)

class TextLookbackStrategy(CompleteStrategy):
    """Fake strategy whose lookback is text instead of a number"""
    INDICATORS = [("rsi", 14)]
    LOOKBACK_WINDOW = "100"

class MorningTradingWindowStrategy(CompleteStrategy):
    """Fake strategy whose window starts after the first candle closes"""
    TRADING_WINDOW = (time(10, 0), time(11, 30))

DELAYED_PROFILE = {"feed": "sip", "lag_minutes": 15, "min_time_frame_minutes": 15}

def candles_starting_at(*new_york_times):
    """Build candles that start at the given New York times, stamped in UTC like Alpaca's"""
    timestamps = [pd.Timestamp(t, tz="America/New_York").tz_convert("UTC") for t in new_york_times]
    return pd.DataFrame({"timestamp": timestamps})

def test_complete_strategy_passes_check_settings():
    """Accept a strategy that sets every required setting"""
    strategy = CompleteStrategy()

    strategy.check_settings(DELAYED_PROFILE)

def test_incomplete_strategy_reports_every_missing_setting():
    """Raise one ValueError naming every missing setting, not just the first"""
    strategy = IncompleteStrategy()

    with pytest.raises(ValueError, match="IncompleteStrategy is missing required settings: NAME, VERSION"):
        strategy.check_settings(DELAYED_PROFILE)

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

def test_unknown_time_frame_fails_check_settings():
    """Reject an unkown TIME_FRAME value at check_settings()"""
    strategy = WrongTimeFrameStrategy()
    with pytest.raises(ValueError, match="is unknown"):
        strategy.check_settings(DELAYED_PROFILE)

def test_time_frame_below_plan_minimum_fails_check_settings():
    """Reject a TIME_FRAME below it's required minimum"""
    strategy = UnderTimeFrameStrategy()
    with pytest.raises(ValueError, match="shorter than the market data plan"):
        strategy.check_settings(DELAYED_PROFILE)

def test_disabled_holding_type_fails_check_settings():
    """Reject an unkown holding type value at check_settings()"""
    strategy = SwingStrategy()
    with pytest.raises(ValueError, match="isn't enabled"):
        strategy.check_settings(DELAYED_PROFILE)

def test_every_invalid_setting_reported_at_once():
    """Confirm all invalid settings are reported instead of failing at one"""
    strategy = MultipleProblemsStrategy()
    with pytest.raises(ValueError) as error:
        strategy.check_settings(DELAYED_PROFILE)
    assert "'1HOUR' is unknown" in str(error.value)
    assert "'swing' isn't enabled" in str(error.value)

def test_valid_trading_window_passes_check_settings():
    """Does not reject a valid trading window"""
    strategy = ValidTradingWindowStrategy()
    strategy.check_settings(DELAYED_PROFILE)

def test_full_regular_hours_window_passes_check_settings():
    """Does not reject the regular market hours window"""
    strategy = MarketTradingWindowStrategy()
    strategy.check_settings(DELAYED_PROFILE)

def test_trading_window_on_session_time_frame_fails_check_settings():
    """Reject any trading window on 'session' time frame"""
    strategy = InvalidKindTradingWindowStrategy()
    with pytest.raises(ValueError, match="invalid kind"):
        strategy.check_settings(DELAYED_PROFILE)

def test_trading_window_start_after_end_fails_check_settings():
    """Reject a trading window where start time > end time"""
    strategy = StartGreaterEndTradingWindowStrategy()
    with pytest.raises(ValueError, match="cannot be at or after end"):
        strategy.check_settings(DELAYED_PROFILE)

def test_trading_window_before_open_fails_check_settings():
    """Reject a trading window where start time is before market hour open"""
    strategy = BeforeOpenTradingWindowStrategy()
    with pytest.raises(ValueError, match="Expected window between"):
        strategy.check_settings(DELAYED_PROFILE)

def test_trading_window_after_close_fails_check_settings():
    """Reject a trading window where close time is after market hour close"""
    strategy = AfterCloseTradingWindowStrategy()
    with pytest.raises(ValueError, match="Expected window between"):
        strategy.check_settings(DELAYED_PROFILE)

def test_trading_window_error_shows_readable_times():
    """Write the window and market hours as HH:MM in the error, not as datetime.time objects"""
    strategy = AfterCloseTradingWindowStrategy()

    with pytest.raises(ValueError, match="Invalid TRADING_WINDOW 09:30-17:00. Expected window between 09:30-16:00"):
        strategy.check_settings(DELAYED_PROFILE)

def test_trading_window_of_strings_fails_check_settings():
    """Reject an invalid value for TRADING_WINDOW and assert ValueError not TypeError"""
    strategy = InvalidValueTradingWindowStrategy()
    with pytest.raises(ValueError):
        strategy.check_settings(DELAYED_PROFILE)

def test_lookback_shorter_than_indicators_fails_check_settings(monkeypatch):
    """Reject a LOOKBACK_WINDOW below the candles its indicators need"""
    monkeypatch.setattr("strategies.base.SEED_TOLERANCE", 0.01)
    strategy = ShortLookbackStrategy()

    with pytest.raises(ValueError) as error:
        strategy.check_settings(DELAYED_PROFILE)

    assert "LOOKBACK_WINDOW 20 is too short. ('rsi', 14) needs 65 candles" in str(error.value)

def test_lookback_equal_to_need_passes_check_settings(monkeypatch):
    """Accept a LOOKBACK_WINDOW exactly equal to the largest need"""
    monkeypatch.setattr("strategies.base.SEED_TOLERANCE", 0.01)
    strategy = ExactLookbackStrategy()

    strategy.check_settings(DELAYED_PROFILE)

def test_lookback_check_names_largest_indicator(monkeypatch):
    """Name the indicator that needs the most candles, not the first one listed"""
    monkeypatch.setattr("strategies.base.SEED_TOLERANCE", 0.01)
    strategy = LargestIndicatorStrategy()

    with pytest.raises(ValueError) as error:
        strategy.check_settings(DELAYED_PROFILE)

    assert "('ema', 200) needs 462 candles" in str(error.value)

def test_lookback_follows_seed_tolerance(monkeypatch):
    """Need fewer candles when SEED_TOLERANCE is looser, so tuning it changes the check"""
    monkeypatch.setattr("strategies.base.SEED_TOLERANCE", 0.05)
    strategy = ShortLookbackStrategy()

    with pytest.raises(ValueError) as error:
        strategy.check_settings(DELAYED_PROFILE)

    assert "('rsi', 14) needs 43 candles at SEED_TOLERANCE 0.05" in str(error.value)

def test_invalid_indicator_fails_check_settings():
    """Report a bad INDICATORS entry as a problem instead of crashing"""
    strategy = InvalidIndicatorStrategy()

    with pytest.raises(ValueError) as error:
        strategy.check_settings(DELAYED_PROFILE)

    assert "INDICATORS entry ('vwap',) is invalid: Unknown indicator 'vwap'" in str(error.value)

def test_indicators_without_outer_list_fails_check_settings():
    """Raise ValueError, not TypeError, when the brackets around INDICATORS are missing"""
    strategy = NoOuterListStrategy()

    with pytest.raises(ValueError) as error:
        strategy.check_settings(DELAYED_PROFILE)

    assert "INDICATORS entry 'rsi' is invalid" in str(error.value)
    assert "INDICATORS entry 14 is invalid" in str(error.value)

def test_text_lookback_fails_check_settings():
    """Raise ValueError, not TypeError, when LOOKBACK_WINDOW isn't a number"""
    strategy = TextLookbackStrategy()

    with pytest.raises(ValueError, match="LOOKBACK_WINDOW '100' is invalid"):
        strategy.check_settings(DELAYED_PROFILE)

def test_no_trading_window_is_always_in_window():
    """Allow buys at any time when TRADING_WINDOW is None"""
    strategy = CompleteStrategy()

    result = strategy.in_trading_window(candles_starting_at("2026-10-19 15:45"))

    assert result is True

def test_candle_closing_inside_window_is_in_window():
    """Allow a buy on a candle that closes between the window's start and end"""
    strategy = ValidTradingWindowStrategy()

    result = strategy.in_trading_window(candles_starting_at("2026-10-19 10:00"))

    assert result is True

def test_candle_closing_at_window_start_is_in_window():
    """Count a candle that closes exactly at the window's start (09:30 candle closes 09:45)"""
    strategy = ValidTradingWindowStrategy()

    result = strategy.in_trading_window(candles_starting_at("2026-10-19 09:30"))

    assert result is True

def test_candle_closing_at_window_end_is_in_window():
    """Count a candle that closes exactly at the window's end (14:00 candle closes 14:15)"""
    strategy = ValidTradingWindowStrategy()

    result = strategy.in_trading_window(candles_starting_at("2026-10-19 14:00"))

    assert result is True

def test_candle_starting_at_window_end_is_outside_window():
    """Judge by close time: a candle that starts at 14:15 closes at 14:30, after the window"""
    strategy = ValidTradingWindowStrategy()

    result = strategy.in_trading_window(candles_starting_at("2026-10-19 14:15"))

    assert result is False

def test_candle_closing_before_window_is_outside_window():
    """Block a buy on a candle that closes before the window starts"""
    strategy = MorningTradingWindowStrategy()

    result = strategy.in_trading_window(candles_starting_at("2026-10-19 09:30"))

    assert result is False

def test_only_last_candle_decides_window():
    """Judge only the newest candle, even when earlier ones closed inside the window"""
    strategy = ValidTradingWindowStrategy()

    result = strategy.in_trading_window(candles_starting_at("2026-10-19 10:00", "2026-10-19 14:15"))

    assert result is False

def test_window_uses_new_york_time_across_daylight_saving():
    """Convert UTC to New York time, so the same UTC time is inside in July and outside in December"""
    strategy = ValidTradingWindowStrategy()
    july = pd.DataFrame({"timestamp": [pd.Timestamp("2026-07-15 13:45", tz="UTC")]})
    december = pd.DataFrame({"timestamp": [pd.Timestamp("2026-12-15 13:45", tz="UTC")]})

    in_july = strategy.in_trading_window(july)
    in_december = strategy.in_trading_window(december)

    assert in_july is True
    assert in_december is False
