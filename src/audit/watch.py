"""
watch.py
Remember between cycles: share mismatches (first seen, last alert, failed checks) and the end-of-day audit
(last reminder, outages)
"""

#Standard Library
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

#Local Imports
from data.market_calendar import NEW_YORK

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

class AuditWatch:
    """What the end-of-day audit remembers between runs; the engine keeps one for as long as it runs

    Lost on a restart, which only means one reminder goes out at once and an outage alert can repeat; open failures
    are read back from audit_log. Outages are kept per cause ("alpaca", "database", "unexpected"), so a new cause
    during an outage still alerts.
    """

    def __init__(self):
        self.last_reminder = None
        self.outages = set()
        self.cap_alerted = False
        self.reminder_read_failed = False

    def reminder_due(self, now: datetime, minutes: int) -> bool:
        """Return True on the first check of a New York day, or once minutes have passed since the last reminder

        Parameters:
            now (datetime): The time now, timezone-aware
            minutes (int): How often the reminder repeats

        Returns:
            True if a reminder should go out now
        """
        if self.last_reminder is None or self.last_reminder.astimezone(ZoneInfo(NEW_YORK)).date() != \
                now.astimezone(ZoneInfo(NEW_YORK)).date():
            return True
        return now - self.last_reminder >= timedelta(minutes=minutes)

    def reminded(self, now: datetime):
        """Note that a reminder just went out

        Parameters:
            now (datetime): The time now, timezone-aware
        """
        self.last_reminder = now

    def outage(self, cause: str) -> bool:
        """Count an audit that couldn't run or save; return True only for the first one of that cause

        Parameters:
            cause (str): "alpaca", "database" (the connection failed), "data" (another database error) or
                "unexpected"

        Returns:
            True if the outage alert should go out
        """
        first = cause not in self.outages
        self.outages.add(cause)
        return first

    def recovered(self, causes: tuple | None = None) -> bool:
        """Note that some causes are over; return True if an outage alert had gone out for one of them

        Parameters:
            causes (tuple | None): The causes that are over; None for all of them

        Returns:
            True if the bot should say the audit runs again
        """
        over = set(self.outages) if causes is None else self.outages & set(causes)
        self.outages -= over
        return bool(over)
