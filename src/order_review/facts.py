"""
facts.py
Hold the OrderFacts snapshot: what the pre-order review knows about the market and the bot's orders at one moment
"""

#Standard Library
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class TradePrice:
    """One ticker's latest real trade: its price and when it happened (timezone-aware)"""
    price: float
    at: datetime

@dataclass(frozen=True)
class OpenOrder:
    """An order of a strategy that isn't done yet (bracket legs left out)"""
    strategy_id: int
    ticker: str
    side: str

@dataclass(frozen=True)
class OrderFacts:
    """Everything the pre-order review knows at one moment, built once per cycle outside the checks

    session_open / session_close are today's regular hours from the trading calendar (None on a day the market
    is closed). price_feed and max_price_age_seconds come from the market data profile. latest_trades holds a
    price only for tickers that had a trade; prices_available is None when no price was asked for, False when
    the request failed. A backtest builds this from its simulation and runs the same checks.
    """
    as_of: datetime
    session_open: datetime | None
    session_close: datetime | None
    price_feed: str
    max_price_age_seconds: float
    latest_trades: dict
    inactive_tickers: frozenset = frozenset()
    open_orders: tuple[OpenOrder, ...] = ()
    prices_available: bool | None = None

    def __post_init__(self):
        """Reject a naive time or half a trading session"""
        if self.as_of.tzinfo is None:
            raise ValueError(f"Invalid timezone {self.as_of.tzinfo!r} for as_of. Expected UTC format")
        if (self.session_open is None) != (self.session_close is None):
            raise ValueError(f"session_open {self.session_open!r} and session_close {self.session_close!r} "
                             "must both be set or both be None")

    def market_open(self) -> bool:
        """Return True between today's open and close, by the real clock"""
        return self.session_open is not None and self.session_open <= self.as_of < self.session_close

    def minutes_to_close(self) -> float | None:
        """Return the minutes left until today's close (negative after it), or None on a closed day"""
        if self.session_close is None:
            return None
        return (self.session_close - self.as_of).total_seconds() / 60

    def has_open_order(self, strategy_id: int, ticker: str, side: str) -> bool:
        """Return True if this strategy already has a buy (or sell) out for this ticker

        Parameters:
            strategy_id (int): The strategy
            ticker (str): The ticker
            side (str): "buy" or "sell"

        Returns:
            True if such an order isn't done yet
        """
        return any(o.strategy_id == strategy_id and o.ticker == ticker and o.side == side for o in self.open_orders)

    def latest_trade(self, ticker: str) -> TradePrice | None:
        """Return a ticker's latest trade, or None if it had none (or prices couldn't be read)"""
        return self.latest_trades.get(ticker)
