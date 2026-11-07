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
ALPACA_TIMEOUT_SECONDS = 10
ORDER_RETRY_WAITS = [1, 2, 4]
STUCK_ORDER_SECONDS = 60
TIME_IN_FORCE = {"day": "day", "swing": "gtc"}
UNKNOWN_ORDER_WAIT_SECONDS = 180
CATCH_UP_SECONDS = 60
CATCH_UP_MARGIN_SECONDS = 300
ACTIVITY_PAGE_SIZE = 100

MARKET_DATA_PLAN = "delayed"
MARKET_DATA_PROFILES = {
    "delayed": {"feed": "sip", "lag_minutes": 15, "min_time_frame_minutes": 15, "price_feed": "iex",
                "max_price_age_seconds": 120},
    "live": {"feed": "sip", "lag_minutes": 0,  "min_time_frame_minutes": 1, "price_feed": "sip",
             "max_price_age_seconds": 60},
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

RISK_PARAMETERS = {
    "position_fraction": {"provider": "static", "value": 0.20, "min": 0.05, "max": 0.25, "max_daily_change": 0.05},
    "drawdown_limit": {"provider": "static", "value": 0.05, "min": 0.04, "max": 0.10, "max_daily_change": 0.01},
    "cooldown_stop_loss": {"provider": "static", "value": 2, "min": 0, "max": 8, "max_daily_change": 2},
    "cooldown_signal": {"provider": "static", "value": 0, "min": 0, "max": 8, "max_daily_change": 2},
    "cooldown_take_profit": {"provider": "static", "value": 0, "min": 0, "max": 8, "max_daily_change": 2},
}
POSITION_SIZER = "fixed_budget"
SHADOW_BUDGET = 250
MAX_LEVERAGE = 1.0
MAX_OPEN_POSITIONS = 10
MAX_POSITIONS_PER_TICKER = 2
MAX_TICKER_FRACTION = 0.15
MAX_ORDER_FRACTION = 0.20
DAILY_HALT_LIMITS = {"day": {"loss": 0.03, "profit": 0.10}}
KILL_SWITCH_FRACTION = 0.05
RISK_EQUITY_CAP = {"PAPER": 1000, "LIVE": None}
LAST_BUY_MINUTES_BEFORE_CLOSE = {"day": 30}
MAX_PRICE_MOVE_OF_STOP = 0.5
SKIP_PRIORITY = ("shadow", "strategy_off", "kill_switch", "audit_mismatch", "drawdown_limit", "daily_halt",
                 "max_leverage", "buying_power", "budget_exhausted", "max_positions", "max_per_ticker",
                 "max_positions_per_ticker", "cooldown", "zero_quantity", "max_order_size", "invalid_exit_prices",
                 "market_closed", "too_late_to_buy", "not_tradable", "open_order", "stale_price", "price_moved",
                 "nothing_to_sell")
