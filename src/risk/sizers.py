"""
sizers.py
Turn a buy request into a share count; the sizer is picked by POSITION_SIZER
"""

#Standard Library
from dataclasses import dataclass
import math

#Local Imports
from risk.context import RiskContext
from risk.decisions import RiskRequest
from risk.parameters import ParameterValue, get_parameter

@dataclass(frozen=True)
class Sizing:
    """What a sizer wants to buy and the parameters it used to decide"""
    quantity: int
    parameters: tuple[ParameterValue, ...]

class FixedBudgetSizer:
    """Give every buy the same slice of the strategy's budget"""
    NAME = "fixed_budget"
    VERSION = "1.0.0"

    def size(self, request: RiskRequest, context: RiskContext) -> Sizing:
        """Return how many whole shares position_fraction of the budget buys at the request's price

        Shadow strategies size from SHADOW_BUDGET, since their real budget is 0.

        Parameters:
            request (RiskRequest): The buy being sized
            context (RiskContext): This cycle's snapshot

        Returns:
            A Sizing with the share count (0 if one share costs more than the slice) and position_fraction
        """
        state = context.strategy(request.strategy_id)
        budget = state.trading_budget
        fraction = get_parameter("position_fraction", request.strategy_id, context)
        dollars = budget * fraction.used
        quantity = math.floor(round(dollars / request.price, 9))
        return Sizing(quantity=quantity, parameters=(fraction,))

SIZERS = {FixedBudgetSizer.NAME: FixedBudgetSizer()}
