"""
audit_samples.py
Shared fake broker, trading calendar and Alpaca activities for the end-of-day audit's integration tests
"""

#Standard Library
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

#Third Party Libraries
import pandas as pd

#Local Imports
from execution.broker import BrokerAccount, BrokerUnavailable

DAY = date(2026, 11, 2)
AFTER_CLOSE = datetime(2026, 11, 2, 21, 30, tzinfo=timezone.utc)
THANKSGIVING = date(2026, 11, 26)

def trading_calendar(start=date(2026, 9, 1), end=date(2026, 12, 31), holidays=(THANKSGIVING,)) -> dict:
    """Return a calendar like get_calendar's: weekdays only, 9:30-16:00 New York, holidays left out"""
    calendar = {}
    day = start
    while day <= end:
        if day.weekday() < 5 and day not in holidays:
            open_time = pd.Timestamp(datetime.combine(day, datetime.min.time()) + timedelta(hours=9, minutes=30))
            close_time = pd.Timestamp(datetime.combine(day, datetime.min.time()) + timedelta(hours=16))
            calendar[day] = {"open": open_time.tz_localize("America/New_York").tz_convert("UTC"),
                             "close": close_time.tz_localize("America/New_York").tz_convert("UTC")}
        day += timedelta(days=1)
    return calendar

def fill_activity(update, *, price=None, quantity=None, fill_id=None) -> dict:
    """Return the FILL activity Alpaca lists for a stream fill; price, quantity or fill_id may differ on purpose"""
    stamp = update.event_at.strftime("%Y%m%d%H%M%S%f")[:17]
    return {"id": f"{stamp}::{fill_id or update.execution_id}", "activity_type": "FILL",
            "transaction_time": update.event_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "type": "fill" if update.status == "filled" else "partial_fill",
            "price": str(price if price is not None else update.fill_price),
            "qty": str(quantity if quantity is not None else update.fill_quantity), "side": update.side,
            "symbol": update.ticker, "leaves_qty": str((update.requested_quantity or 0) - update.filled_quantity),
            "order_id": update.alpaca_order_id, "cum_qty": str(update.filled_quantity),
            "order_status": update.status}

def dated_activity(activity_type, net_amount, on=DAY, number=1) -> dict:
    """Return a non-fill activity (a fee, deposit, dividend) that Alpaca stamps with a date only"""
    return {"id": f"{on:%Y%m%d}000000000::{activity_type.lower()}-{number}", "activity_type": activity_type,
            "date": on.isoformat(), "net_amount": str(net_amount), "status": "executed"}

class FakeAuditBroker:
    """Stands in for AlpacaBroker: lists the activities, cash and positions it was given, or raises"""

    def __init__(self, activities=(), cash="1000", positions=None, error=None):
        self.activities = list(activities)
        self.cash = None if cash is None else Decimal(cash)
        self.positions = positions or {}
        self.error = error
        self.calls = []

    def _check(self):
        if self.error:
            raise BrokerUnavailable(self.error)

    def get_activities(self, since, until):
        self.calls.append(("get_activities", since, until))
        self._check()
        return list(self.activities)

    def get_account(self):
        self._check()
        return BrokerAccount(Decimal("1000"), Decimal("1000"), Decimal("1000"), cash=self.cash)

    def get_positions(self):
        self._check()
        return dict(self.positions)

class Alerts:
    """Records alerts instead of sending them"""

    def __init__(self):
        self.sent = []

    def __call__(self, message):
        self.sent.append(message)
