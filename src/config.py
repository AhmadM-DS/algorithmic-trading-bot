"""
config.py
Global configuration settings for the trading bot.
"""

DEFAULT_FILTERS = [
    {"left": "close", "operation": "in_range", "right": [2, 20]},
    {"left": "change", "operation": "greater", "right": 10},
    {"left": "relative_volume_10d_calc", "operation": "greater", "right": 5},
    {"left": "float_shares_outstanding_current", "operation": "in_range", "right": [1000000, 10000000]}
]