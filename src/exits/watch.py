"""
watch.py
Remember between cycles which positions are being closed and which alerts already went out
"""

#Standard Library
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass(frozen=True)
class Closing:
    """One position the bot is closing: why, and since when (naive UTC)"""
    exit_reason: str
    since: datetime

class ExitWatch:
    """What the exits remember between cycles; the engine keeps one for as long as it runs

    Lost on a restart, which only restarts the stuck-close clock: the positions themselves are found again from
    the database (end-of-day, earlier-day leftovers and sells already tried).
    """

    def __init__(self):
        self.closing = {}
        self._sent = set()

    def start(self, position_id: int, exit_reason: str, now: datetime):
        """Start the clock on a close, keeping the first reason and time if it's already running

        Parameters:
            position_id (int): The position being closed
            exit_reason (str): Why, e.g. "end_of_day" or "signal"
            now (datetime): The time now, naive UTC
        """
        self.closing.setdefault(position_id, Closing(exit_reason, now))

    def reason(self, position_id: int) -> str | None:
        """Return the exit reason a running close started with, or None if the position isn't being closed

        Parameters:
            position_id (int): The position

        Returns:
            The exit reason, or None
        """
        closing = self.closing.get(position_id)
        return closing.exit_reason if closing else None

    def forget(self, position_id: int):
        """Stop tracking a position that's closed

        Parameters:
            position_id (int): The position
        """
        self.closing.pop(position_id, None)

    def first_time(self, key: tuple) -> bool:
        """Return True the first time a key is seen, so each alert goes out once

        Parameters:
            key (tuple): What the alert is about, e.g. ("leftover", 42)

        Returns:
            True if the key is new
        """
        if key in self._sent:
            return False
        self._sent.add(key)
        return True

    def stuck(self, position_id: int, now: datetime, minutes: int) -> bool:
        """Return True once when a close has been running for at least minutes

        Parameters:
            position_id (int): The position
            now (datetime): The time now, naive UTC
            minutes (int): How long a close may run before it counts as stuck

        Returns:
            True only on the first check past the limit
        """
        closing = self.closing.get(position_id)
        if closing is None or now - closing.since < timedelta(minutes=minutes):
            return False
        return self.first_time(("stuck", position_id, closing.since))
