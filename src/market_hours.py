"""
market_hours.py
Handles when trades can happen even during market hours.
"""

#Standard Library
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

#Local imports
from alpaca_client import api
from logger import get_logger
logger = get_logger(__name__)

MARKET_TZ = ZoneInfo("America/New_York")

def is_market_open():
    clock = api.get_clock()
    return clock.is_open

def is_weekend():
    return datetime.now(MARKET_TZ).weekday() >= 5

def market_time_slots(start="09:30", end="16:00", interval=15):
    slots = []
    current = datetime.strptime(start, "%H:%M")
    end_time = datetime.strptime(end, "%H:%M")
    while current <= end_time:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=interval)
    return slots

def is_within_window(start_time, end_time):
    """
    Check if the current time falls within
    [start_time, end_time].

    Parameters:
        start_time (str): Window start, "HH:MM".
        end_time (str): Window end, "HH:MM".
    """
    now = datetime.now(MARKET_TZ).time()
    start = datetime.strptime(start_time, "%H:%M").time()
    end = datetime.strptime(end_time, "%H:%M").time()
    return start <= now <= end