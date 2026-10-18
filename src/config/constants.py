"""
constants.py
Global constants for the trading bot.
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
PER_TRADE_PROFIT_TARGET_PCT = 0.05
PER_TRADE_STOP_LOSS_PCT = 0.05
RISK_FRACTION = 0.25
INITIAL_CAPITAL = 10000
TRADING_INTERVAL = 15
RELATIVE_VOLUME_LOOKBACK_DAYS = 10
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
MAX_TICKERS = 20
#Temporarily in constants.py until system logging is finished
UNATTENDED_UPGRADES_LOG_PATH = "/var/log/unattended-upgrades/unattended-upgrades.log"

DISCORD_MENTION = "<@375084779256676353>"
MARKET_OPEN_TIME = "09:30"
MARKET_CLOSE_TIME = "16:00"
CLOSING_STATUS_TIME = "16:01"

MAX_CALLS = 180
WINDOW_SECONDS = 60
RATE_LIMIT_ALERT_THRESHOLD = 20
RATE_LIMIT_ALERT_COOLDOWN_SECONDS = 300

MARKET_DATA_PLAN = "delayed"
MARKET_DATA_PROFILES = {
    "delayed": {"feed": "sip", "lag_minutes": 15, "min_time_frame_minutes": 15},
    "live":    {"feed": "sip", "lag_minutes": 0,  "min_time_frame_minutes": 1},
}
PRICE_ADJUSTMENT = "split"
SEED_TOLERANCE = 0.01
ENABLED_HOLDING_TYPES = ["day"]


DATA_HEALTH_SAVE = "failures"
DATA_HEALTH_THRESHOLDS = {
    "max_missing_candles": 2,
    "stale_after_candles": 1,
    "max_zero_volume": 0,
}

MIN_TRADES_FOR_POPULAR = 3
SCREENER_SOURCE = "biggest-gainers"
