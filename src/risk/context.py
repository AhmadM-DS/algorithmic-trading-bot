"""
context.py
Hold the RiskContext snapshot: everything risk knows about the account at one moment
"""

#Standard Library
from dataclasses import dataclass, field
from datetime import datetime

#Local Imports
from config.constants import SHADOW_BUDGET

STRATEGY_MODES = ("off", "shadow", "live")

@dataclass(frozen=True)
class ParameterValue:
    """One parameter as proposed by its provider and as actually used after the bounds"""
    name: str
    provider: str
    proposed: float
    used: float
    limited_by: tuple[str, ...]

@dataclass(frozen=True)
class RiskEvent:
    """A risk state that started this cycle (or stopped, for states that don't lock), to save and alert once

    channel is "critical" or "trades"; strategy_id is None for an account-wide state.
    """
    event_type: str
    strategy_id: int | None
    channel: str
    message: str

@dataclass(frozen=True)
class StrategyState:
    """One strategy's mode, the budget risk may use this cycle, and the halts it's under

    daily_pnl is today's realized P/L per holding type. drawdown is how far the realized P/L since the budget
    was set is below its peak (0 or more). drawdown_limit is the parameter the drawdown was checked against,
    saved with each decision.
    """
    strategy_id: int
    mode: str
    effective_budget: float
    name: str = ""
    budget: float = 0.0
    daily_pnl: dict = field(default_factory=dict)
    drawdown: float = 0.0
    halted_holding_types: frozenset = frozenset()
    drawdown_paused: bool = False
    drawdown_limit: ParameterValue | None = None

    def __post_init__(self):
        """Reject an unknown mode or a negative budget"""
        if self.mode not in STRATEGY_MODES:
            raise ValueError(f"Invalid mode {self.mode!r}. Expected one of {list(STRATEGY_MODES)}")
        if not self.effective_budget >= 0:
            raise ValueError(f"Invalid effective_budget {self.effective_budget!r}. Expected a value of 0 or more.")

    @property
    def trading_budget(self) -> float:
        """Return the budget this strategy sizes and checks against: SHADOW_BUDGET in shadow, else effective_budget"""
        return SHADOW_BUDGET if self.mode == "shadow" else self.effective_budget

    def pnl_today(self, holding_type: str) -> float:
        """Return today's realized P/L for one holding type, 0 if nothing of that type closed today

        Parameters:
            holding_type (str): "day" or "swing"

        Returns:
            The P/L in dollars
        """
        return self.daily_pnl.get(holding_type, 0.0)

@dataclass(frozen=True)
class OpenPosition:
    """One open position as the database sees it"""
    position_id: int
    strategy_id: int
    ticker: str
    holding_type: str
    shares_held: int
    avg_entry_price: float

    @property
    def cost(self) -> float:
        """Return the money tied up in this position at entry"""
        return self.shares_held * self.avg_entry_price

@dataclass(frozen=True)
class RecentExit:
    """One position closed today, used for cooldowns"""
    strategy_id: int
    ticker: str
    exit_reason: str
    closed_at: datetime

@dataclass(frozen=True)
class BrokerPosition:
    """How many shares of one ticker Alpaca holds for the whole account"""
    ticker: str
    shares: int

@dataclass(frozen=True)
class RiskContext:
    """Everything risk knows at one moment, built once per cycle outside risk

    equity is capped by RISK_EQUITY_CAP. account_daily_change is Alpaca's equity minus last_equity (uncapped
    dollars); start_equity is the capped last_equity, the kill switch's base. scale_down is the factor every
    live budget was multiplied by (1.0 when the account covers them). previous_parameters holds the last value
    used before today for each (strategy_id, name). events are the states that started this cycle.
    """
    as_of: datetime
    equity: float
    buying_power: float
    strategies: tuple[StrategyState, ...]
    open_positions: tuple[OpenPosition, ...]
    recent_exits: tuple[RecentExit, ...]
    broker_positions: tuple[BrokerPosition, ...]
    account_daily_change: float = 0.0
    start_equity: float = 0.0
    kill_switch: bool = False
    scale_down: float = 1.0
    previous_parameters: dict = field(default_factory=dict)
    events: tuple[RiskEvent, ...] = ()

    def __post_init__(self):
        """Reject a naive as_of time"""
        if self.as_of.tzinfo is None:
            raise ValueError(f"Invalid timezone {self.as_of.tzinfo!r} for as_of. Expected UTC format")

    def strategy(self, strategy_id: int) -> StrategyState:
        """Return one strategy's state

        Parameters:
            strategy_id (int): The strategy's id in the strategies table

        Returns:
            Its StrategyState

        Raises:
            ValueError if the strategy isn't in this snapshot
        """
        state = next((s for s in self.strategies if s.strategy_id == strategy_id), None)
        if state is None:
            raise ValueError(f"strategy_id {strategy_id!r} isn't in this snapshot. Expected one of {[s.strategy_id for s in self.strategies]}")
        return state

    def positions(self, strategy_id: int | None = None, ticker: str | None = None) -> tuple[OpenPosition, ...]:
        """Return the open positions matching a strategy and / or ticker

        None means any, so positions() returns every open position.

        Parameters:
            strategy_id (int | None): Only this strategy's positions
            ticker (str | None): Only this ticker's positions

        Returns:
            A tuple of OpenPosition, empty if none match
        """
        return tuple(p for p in self.open_positions if (
            (strategy_id is None or p.strategy_id == strategy_id)
            and (ticker is None or p.ticker == ticker)
        ))

    def exposure(self, strategy_id: int | None = None, ticker: str | None = None) -> float:
        """Return the money tied up in matching open positions, at entry prices

        Parameters:
            strategy_id (int | None): Only this strategy's positions
            ticker (str | None): Only this ticker's positions

        Returns:
            The summed cost, 0 if nothing matches
        """
        return sum(p.cost for p in self.positions(strategy_id, ticker))

    def shares_held(self, strategy_id: int, ticker: str) -> int:
        """Return how many shares of a ticker one strategy holds across its open positions

        Parameters:
            strategy_id (int): The strategy
            ticker (str): The ticker

        Returns:
            The share count, 0 if none
        """
        return sum(p.shares_held for p in self.positions(strategy_id, ticker))

    def broker_shares(self, ticker: str) -> int:
        """Return how many shares of a ticker Alpaca holds for the whole account

        Parameters:
            ticker (str): The ticker

        Returns:
            The share count, 0 if Alpaca holds none
        """
        held = next((b for b in self.broker_positions if b.ticker == ticker), None)
        return 0 if held is None else held.shares

    def previous(self, strategy_id: int, name: str) -> float | None:
        """Return the value a strategy last used for a parameter before today, for the rate limit

        Parameters:
            strategy_id (int): The strategy
            name (str): A key in RISK_PARAMETERS

        Returns:
            The value, or None if it never used it before today
        """
        return self.previous_parameters.get((strategy_id, name))

    def last_exit(self, strategy_id: int, ticker: str) -> RecentExit | None:
        """Return a strategy's most recent exit from a ticker today

        Parameters:
            strategy_id (int): The strategy
            ticker (str): The ticker

        Returns:
            The newest RecentExit, or None if it hasn't exited that ticker today
        """
        exits = (e for e in self.recent_exits if e.strategy_id == strategy_id and e.ticker == ticker)
        return max(exits, key=lambda e: e.closed_at, default=None)
