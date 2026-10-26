"""
decisions.py
Hold what the engine asks risk (RiskRequest) and what risk answers (Decision)
"""

#Standard Library
from dataclasses import dataclass

#Local Imports
from strategies.signals import Signal
from risk.parameters import ParameterValue

@dataclass(frozen=True)
class RiskRequest:
    """One signal asking risk for permission and a quantity"""
    signal: Signal
    strategy_id: int
    price: float

    def __post_init__(self):
        """Reject a price that can't be used for sizing"""
        if not self.price > 0:
            raise ValueError(f"price {self.price!r} can't be used for sizing. Expected a number above 0, not a zero, negative or missing price")

@dataclass(frozen=True)
class Decision:
    """Risk's answer: how many shares to trade, or why none"""
    approved_quantity: int
    skip_reason: str | None
    failed_checks: tuple[str, ...]
    sizer: str
    sized_quantity: int
    parameters: tuple[ParameterValue, ...] = ()

    def __post_init__(self):
        """Reject a Decision that contradicts itself"""
        if min(self.approved_quantity, self.sized_quantity) < 0:
            raise ValueError(f"approved_quantity {self.approved_quantity!r} or sized_quantity {self.sized_quantity!r} is less than 0. Expected 0 or more")
        approved = self.approved_quantity > 0
        if ((approved and self.skip_reason is not None)
            or (not approved and self.skip_reason is None)):
            raise ValueError(f"approved_quantity {self.approved_quantity!r} rejected with skip_reason {self.skip_reason!r}. Expected a skip_reason only when approved_quantity is 0")
        if approved and self.failed_checks:
            raise ValueError(f"approved_quantity {self.approved_quantity!r} has failed_checks {self.failed_checks!r}. An approved Decision has no failures")
        if not approved and (not self.failed_checks or self.skip_reason != self.failed_checks[0]):
            raise ValueError(f"skip_reason {self.skip_reason!r} isn't the top failure in failed_checks {self.failed_checks!r}. Expected it to be failed_checks[0]")
        if self.approved_quantity > self.sized_quantity:
            raise ValueError(f"approved_quantity {self.approved_quantity!r} is more than sized_quantity {self.sized_quantity!r}. Guardrails can only cut the sizer's quantity")
