"""
WarriorTrading.py
Implementing the Momentum trading strategy by Warrior Trading.
"""

#Standard Library
#Third party library
#Local Imports
from strategies.base_strategy import Strategy
from logger import get_logger
from market_hours import is_within_window
logger = get_logger(__name__)

"""
Strategy Workflow
"""

class Momentum(Strategy):
    trading_window = ("09:30", "11:00")
    
    def generate_signals(self):
        if not is_within_window(*self.trading_window):
            self.df.loc[self.df.index[-1], "signal"] = 0
            return
        raise NotImplementedError
    #Write the rest of this strategy after completing the technical indicators file