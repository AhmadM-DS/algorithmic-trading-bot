import pytest
from risk import DailyRiskState

def test_duplicate_buy_is_noop():
    """Tests for duplicate buy/sell orders"""
    state = DailyRiskState()
    state.record_buy("AAPL", "MACD", price=100.0, quantity=10)
    state.record_buy("AAPL", "MACD", price=200.0, quantity=5)
    assert state.strategy_cost_basis["MACD"] == 1000.0

def test_sell_without_prior_buy_does_not_change_pnl():
    state = DailyRiskState()
    state.record_sell("AAPL", "MACD", price=100.0, quantity=10)
    assert "MACD" not in state.strategy_realized_pnl

def test_is_halted_sticky_after_profit_target(monkeypatch):
    monkeypatch.setattr("risk.send_routine", lambda *a, **k: None)
    state = DailyRiskState()
    state.record_buy("AAPL", "MACD", price=100.0, quantity=10)
    state.record_sell("AAPL", "MACD", price=115, quantity=10)
    assert state.is_halted("MACD") is True
    state.record_buy("MSFT", "MACD", price=115.0, quantity=10)
    state.record_sell("MSFT", "MACD", price=95, quantity=10)
    assert state.is_halted("MACD") is True