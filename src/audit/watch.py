"""
watch.py
Remember between cycles when each share mismatch was first seen, when it was last alerted and failed checks
"""

#Standard Library
from datetime import datetime, timedelta

class ReconciliationWatch:
    """What reconciliation remembers between cycles; the engine keeps one for as long as it runs

    Lost on a restart, which only restarts the clocks: a mismatch not recorded yet waits the full time again, and
    recorded mismatches are read back from bot_events, so none is saved twice.
    """

    def __init__(self):
        self.first_seen = {}
        self.last_alert = {}
        self.failed_checks = 0
        self._failure_alerted = False

    def seen(self, ticker: str, now: datetime) -> datetime:
        """Start the clock on a mismatch, keeping the first time if it's already running

        Parameters:
            ticker (str): The mismatched ticker
            now (datetime): The time now, naive UTC

        Returns:
            When this mismatch was first seen, naive UTC
        """
        return self.first_seen.setdefault(ticker, now)

    def forget(self, ticker: str):
        """Stop tracking a ticker whose counts match again

        Parameters:
            ticker (str): The ticker
        """
        self.first_seen.pop(ticker, None)
        self.last_alert.pop(ticker, None)

    def alerted(self, ticker: str, now: datetime):
        """Note that a mismatch alert just went out, so the next repeat waits a full period

        Parameters:
            ticker (str): The ticker
            now (datetime): The time now, naive UTC
        """
        self.last_alert[ticker] = now

    def repeat_due(self, ticker: str, recorded_at: datetime, now: datetime, minutes: int) -> bool:
        """Return True if a recorded mismatch's alert hasn't gone out for at least minutes

        With no alert remembered (after a restart), the time it was recorded counts as the last alert.

        Parameters:
            ticker (str): The ticker
            recorded_at (datetime): When the mismatch row was saved, naive UTC
            now (datetime): The time now, naive UTC
            minutes (int): How often the alert repeats

        Returns:
            True if the alert should go out again now
        """
        last = self.last_alert.get(ticker, recorded_at)
        return now - last >= timedelta(minutes=minutes)

    def check_failed(self, limit: int) -> bool:
        """Count one check that couldn't run; return True once, when the count reaches limit

        Parameters:
            limit (int): How many failed checks in a row send the alert

        Returns:
            True only on the check that reaches the limit
        """
        self.failed_checks += 1
        if self.failed_checks >= limit and not self._failure_alerted:
            self._failure_alerted = True
            return True
        return False

    def check_ran(self) -> bool:
        """Reset the failed count after a check that ran; return True if a failure alert had gone out

        Returns:
            True if the bot should say checks are running again
        """
        was_alerted = self._failure_alerted
        self.failed_checks = 0
        self._failure_alerted = False
        return was_alerted
