"""
config.py
Global configuration settings for the trading bot.
"""

DEFAULT_FILTERS = {
    "price_min": 2,
    "price_max": 20,
    "change_min": 10,
    "relative_volume_min": 5,
    "float_min": 1_000_000,
    "float_max": 10_000_000,
}
DEFAULT_PROFIT_TARGET = 0.10
DEFAULT_LOSS_LIMIT = -0.05
DEFAULT_LOOKBACK_DAYS = 300