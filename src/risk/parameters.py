"""
parameters.py
Get tunable risk parameters from their provider and keep them inside their bounds
"""

#Standard Library
from dataclasses import dataclass
import math

#Local Imports
from config.constants import RISK_PARAMETERS
from risk.context import RiskContext
from logger import health_log

@dataclass(frozen=True)
class ParameterValue:
    """One parameter as proposed by its provider and as actually used after the bounds"""
    name: str
    provider: str
    proposed: float
    used: float
    limited_by: tuple[str, ...]

def apply_bounds(name: str, proposed: float, previous: float | None) -> tuple[float, tuple[str, ...]]:
    """Clamp a proposed value to its min and max, then limit how far it moved from the previous value

    Parameters:
        name (str): A key in RISK_PARAMETERS
        proposed (float): The provider's value
        previous (float | None): The value used last time; None skips the rate limit

    Returns:
        (used value, limited_by)
    """
    settings = RISK_PARAMETERS[name]
    used = proposed
    limited_by = []

    low = settings["min"]
    high = settings["max"]
    if used < low:
        used = low
        limited_by.append("clamp")
    elif used > high:
        used = high
        limited_by.append("clamp")

    if previous is not None:
        low = previous - settings["max_daily_change"]
        high = previous + settings["max_daily_change"]
        if used < low:
            used = low
            limited_by.append("rate_limit")
        elif used > high:
            used = high
            limited_by.append("rate_limit")

    return used, tuple(limited_by)

class StaticProvider:
    """Propose each parameter's fixed value from RISK_PARAMETERS"""
    NAME = "static"
    VERSION = "1.0.0"

    def propose(self, name: str, strategy_id: int, context: RiskContext) -> float:
        """Return the parameter's static value

        Parameters:
            name (str): A key in RISK_PARAMETERS
            strategy_id (int): The strategy asking
            context (RiskContext): This cycle's snapshot

        Returns:
            The value from RISK_PARAMETERS
        """

        return RISK_PARAMETERS[name]["value"]

PROVIDERS = {StaticProvider.NAME: StaticProvider()}

def get_parameter(name: str, strategy_id: int, context: RiskContext, previous: float | None = None) -> ParameterValue:
    """Return a tunable parameter from its provider, kept inside its bounds

    If the provider crashes or returns something that isn't a finite number, the static value
    is used instead and limited_by is ("fallback",), so trading never stops over a broken model.

    Parameters:
        name (str): A key in RISK_PARAMETERS
        strategy_id (int): The strategy asking
        context (RiskContext): This cycle's snapshot
        previous (float | None): The value used last time; None skips the rate limit

    Returns:
        A ParameterValue with what the provider proposed and what is actually used
    """
    settings = RISK_PARAMETERS[name]
    provider = PROVIDERS[settings["provider"]]
    label = f"{provider.NAME}:{provider.VERSION}"

    try:
        proposed = provider.propose(name, strategy_id, context)
    except Exception as e:
        health_log.warning(f"Provider {label} failed on {name}, using the static value: {e}")
        return ParameterValue(name=name, provider=label, proposed=float("nan"), used=settings["value"], limited_by=("fallback",))

    if not _is_finite_number(proposed):
        health_log.warning(f"Provider {label} returned {proposed!r} for {name}, using the static value")
        return ParameterValue(name=name, provider=label, proposed=float("nan"), used=settings["value"], limited_by=("fallback",))

    used, limited_by = apply_bounds(name=name, proposed=proposed, previous=previous)
    return ParameterValue(name=name, provider=label, proposed=proposed, used=used, limited_by=limited_by)

def _is_finite_number(value) -> bool:
    """Return True for an int or float that isn't NaN or infinite"""
    return isinstance(value, (int, float)) and math.isfinite(value)
