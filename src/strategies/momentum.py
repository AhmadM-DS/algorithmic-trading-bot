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
from config import DEFAULT_FILTERS
logger = get_logger(__name__)

"""
Strategy Workflow
"""

class Momentum(Strategy):
    ...
    #Write this strategy after completing the technical indicators file