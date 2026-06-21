"""
market_hours.py
Handles when trades can happen even during market hours.
"""

#Standard Library
from datetime import datetime, timedelta

#Local imports
from alpaca_client import api
from logger import get_logger
logger = get_logger(__name__)

def is_market_open():
    clock = api.get_clock()
    return clock.is_open

def market_time_slots(start="09:30", end="16:00", interval=15):
    slots = []
    current = datetime.strptime(start, "%H:%M")
    end_time = datetime.strptime(end, "%H:%M")
    while current <= end_time:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=interval)
    return slots

def is_within_window(start_time, end_time):
    #Check if the current time falls between start and end
    pass