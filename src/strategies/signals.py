"""
signals.py
Hold the Signal a strategy returns when it wants to buy or sell
"""

#Standard Library
from dataclasses import dataclass

@dataclass(frozen=True)
class Signal:
    """What a strategy decided and why; the engine adds quantity, timing and the skip result"""
    side: str
    time_frame: str
    holding_type: str
    stop_price: float | None
    target_price: float | None
    reason: str
    strategy_version: str
    ticker: str
    features: dict
