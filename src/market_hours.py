"""
market_hours.py
Handles when trades can happen even during market hours.
"""

#Standard Library
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

#Local imports
from config.constants import TRADING_INTERVAL, MARKET_OPEN_TIME
from logger import legacy_log as logger

MARKET_TZ = ZoneInfo("America/New_York")


def is_market_open(api):
    clock = api.get_clock()
    return clock.is_open

def is_weekend():
    return datetime.now(MARKET_TZ).weekday() >= 5

def market_time_slots(start=MARKET_OPEN_TIME, end="16:00", interval=TRADING_INTERVAL):
    slots = []
    current = datetime.strptime(start, "%H:%M")
    end_time = datetime.strptime(end, "%H:%M")
    while current <= end_time:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=interval)
    return slots