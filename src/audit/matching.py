"""
matching.py
The end-of-day audit's pure parts: read Alpaca's activities, match its fills to the database's, check the cash
"""

#Standard Library
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

#Third Party Libraries
import pandas as pd

#Local Imports
from data.market_calendar import NEW_YORK
from fills.events import UNREADABLE_ERRORS
from storage.fills import TICKER_LENGTH, fits_ticker

PRICE_PLACES = Decimal("0.0001")
ACTIVITY_TYPE_LENGTH = 10
ID_LENGTH = 128
LARGEST_AMOUNT = Decimal("1e15")
DAY_KINDS = ("missing_in_db", "missing_at_alpaca", "price_mismatch", "quantity_mismatch", "order_fill_mismatch",
             "unreadable_activity", "untracked_symbol")
NOW_KINDS = ("share_mismatch", "cash")
NOT_BLOCKING_KINDS = NOW_KINDS

@dataclass(frozen=True)
class Fill:
    """One fill as one side reports it: Alpaca's activity or the database's trades row"""
    fill_id: str
    ticker: str
    side: str
    quantity: Decimal
    price: Decimal

    def as_details(self) -> dict:
        """Return the fill's numbers as text, for a failure's JSON details"""
        return {"side": self.side, "quantity": str(self.quantity), "price": str(self.price)}

@dataclass(frozen=True)
class Failure:
    """One problem an audit found; ticker is None for cash, an unreadable activity and an untracked symbol"""
    kind: str
    ticker: str | None
    fill_id: str | None = None
    details: dict = field(default_factory=dict)

@dataclass(frozen=True)
class FillMatch:
    """Alpaca's fills for one day against the database's, after the audit's repairs

    missing_in_db and missing_at_alpaca hold Fills; price_mismatches and quantity_mismatches hold
    (alpaca, database) pairs.
    """
    missing_in_db: tuple = ()
    missing_at_alpaca: tuple = ()
    price_mismatches: tuple = ()
    quantity_mismatches: tuple = ()

    def failures(self) -> list:
        """Return one Failure per problem, missing fills first

        Returns:
            A list of Failure
        """
        found = [Failure("missing_in_db", item.ticker, item.fill_id, {"alpaca": item.as_details()})
                 for item in self.missing_in_db]
        found += [Failure("missing_at_alpaca", item.ticker, item.fill_id, {"database": item.as_details()})
                  for item in self.missing_at_alpaca]
        for kind, pairs in (("price_mismatch", self.price_mismatches), ("quantity_mismatch", self.quantity_mismatches)):
            found += [Failure(kind, alpaca.ticker, alpaca.fill_id,
                              {"alpaca": alpaca.as_details(), "database": database.as_details()})
                      for alpaca, database in pairs]
        return found

def day_window(audit_date: date) -> tuple:
    """Return one New York day as naive UTC times, midnight to midnight

    Parameters:
        audit_date (date): The New York date

    Returns:
        (start, end), naive UTC; end is the next day's start
    """
    start = datetime.combine(audit_date, time(0), ZoneInfo(NEW_YORK))
    end = datetime.combine(audit_date + timedelta(days=1), time(0), ZoneInfo(NEW_YORK))
    return (start.astimezone(timezone.utc).replace(tzinfo=None), end.astimezone(timezone.utc).replace(tzinfo=None))

def is_fill_activity(activity: dict) -> bool:
    """Return True for a FILL activity (a trade), False for the rest (fees, deposits, dividends, splits)"""
    return activity.get("activity_type") == "FILL"

def _activity_time(activity: dict) -> datetime:
    """Return a fill's transaction time, or the start of a dated activity's New York day, as naive UTC"""
    if activity.get("transaction_time"):
        moment = pd.Timestamp(activity["transaction_time"]).floor("us").tz_convert("UTC")
        return moment.tz_localize(None).to_pydatetime()
    return day_window(date.fromisoformat(activity["date"]))[0]

def _decimal(value) -> Decimal | None:
    """Turn one of Alpaca's number strings into a Decimal, keeping None"""
    return None if value is None else Decimal(str(value))

def _side(value) -> str | None:
    """Return "buy", "sell" (for any kind of sell) or None"""
    if value is None:
        return None
    return "buy" if value == "buy" else "sell"

def _ticker(symbol) -> str | None:
    """Return the symbol if it fits the ticker column; an option's longer symbol stays only in the raw JSON"""
    return symbol if fits_ticker(symbol) else None

def activity_day(activity: dict) -> date | None:
    """Return the New York day an activity belongs to, from its transaction time, its date or its ID's
    YYYYMMDD prefix, whichever can be read first

    Parameters:
        activity (dict): One item from AlpacaBroker.get_activities, readable or not

    Returns:
        A date, or None if none of the three can be read
    """
    try:
        return pd.Timestamp(activity["transaction_time"]).tz_convert(NEW_YORK).date()
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    try:
        return date.fromisoformat(activity["date"])
    except (KeyError, TypeError, ValueError):
        pass
    try:
        return datetime.strptime(str(activity["id"])[:8], "%Y%m%d").date()
    except (KeyError, TypeError, ValueError):
        return None

def _fitting_text(value, length: int, name: str):
    """Return a text value that fits its column, or raise ValueError"""
    if value is not None and len(str(value)) > length:
        raise ValueError(f"{name} is too long for its column ({len(str(value))} characters, at most {length})")
    return value

def _fitting_decimal(value, name: str) -> Decimal | None:
    """Return a number as a Decimal that fits DECIMAL(19,4), or raise ValueError"""
    number = _decimal(value)
    if number is not None and abs(number) >= LARGEST_AMOUNT:
        raise ValueError(f"{name} {value} is too big for its column")
    return number

def activity_record(activity: dict) -> dict:
    """Return one activity as an account_activities row, the whole message kept raw

    Parameters:
        activity (dict): One item from AlpacaBroker.get_activities

    Returns:
        {"alpaca_activity_id", "alpaca_order_id", "activity_type", "activity_at" (naive UTC), "ticker", "side",
        "quantity", "price", "net_amount", "raw_json"}; numbers as Decimal, missing values None

    Raises:
        One of UNREADABLE_ERRORS if Alpaca left out or garbled a field every activity has, or sent a value too big for
        its column
    """
    return {"alpaca_activity_id": _fitting_text(activity["id"], ID_LENGTH, "id"),
            "alpaca_order_id": _fitting_text(activity.get("order_id"), ID_LENGTH, "order_id"),
            "activity_type": _fitting_text(activity["activity_type"], ACTIVITY_TYPE_LENGTH, "activity_type"),
            "activity_at": _activity_time(activity), "ticker": _ticker(activity.get("symbol")),
            "side": _side(activity.get("side")), "quantity": _fitting_decimal(activity.get("qty"), "qty"),
            "price": _fitting_decimal(activity.get("price"), "price"),
            "net_amount": _fitting_decimal(activity.get("net_amount"), "net_amount"),
            "raw_json": json.dumps(activity)}

def alpaca_fill(activity: dict) -> Fill:
    """Return a FILL activity as a Fill, its ID being the execution ID after the "::"

    Parameters:
        activity (dict): One FILL activity

    Returns:
        A Fill
    """
    return Fill(activity["id"].split("::")[-1], activity["symbol"], _side(activity["side"]),
                Decimal(str(activity["qty"])), Decimal(str(activity["price"])))

def _same_price(alpaca: Decimal, database: Decimal) -> bool:
    """Compare two prices at the database's 4 decimals, rounding halves away from zero as SQL Server does"""
    return (alpaca.quantize(PRICE_PLACES, rounding=ROUND_HALF_UP)
            == database.quantize(PRICE_PLACES, rounding=ROUND_HALF_UP))

def match_fills(alpaca: list, database: list) -> FillMatch:
    """Match one day's fills by fill ID and compare their side, quantity and price

    Parameters:
        alpaca (list): Fills from Alpaca's FILL activities
        database (list): Fills from the database's current trades rows

    Returns:
        A FillMatch; a different side counts as a quantity mismatch
    """
    at_alpaca = {item.fill_id: item for item in alpaca}
    in_db = {item.fill_id: item for item in database}
    prices, quantities = [], []
    for fill_id in sorted(set(at_alpaca) & set(in_db)):
        pair = (at_alpaca[fill_id], in_db[fill_id])
        if pair[0].side != pair[1].side or pair[0].quantity != pair[1].quantity:
            quantities.append(pair)
        elif not _same_price(pair[0].price, pair[1].price):
            prices.append(pair)
    return FillMatch(missing_in_db=tuple(at_alpaca[key] for key in sorted(set(at_alpaca) - set(in_db))),
                     missing_at_alpaca=tuple(in_db[key] for key in sorted(set(in_db) - set(at_alpaca))),
                     price_mismatches=tuple(prices), quantity_mismatches=tuple(quantities))

def cash_failure(alpaca_cash: Decimal, expected_cash: Decimal, tolerance: float, activities: list) -> Failure | None:
    """Return a cash failure if Alpaca's cash and the expected cash differ by more than the tolerance

    Parameters:
        alpaca_cash (Decimal): Alpaca's cash now
        expected_cash (Decimal): Starting cash plus every movement the database knows since
        tolerance (float): The largest difference that counts as rounding
        activities (list): The day's non-fill activities ({"activity_type", "net_amount", "activity_at"}), listed in
            the failure so the owner can see what moved the cash

    Returns:
        A Failure of kind "cash", or None if the cash matches
    """
    difference = alpaca_cash - expected_cash
    if abs(difference) <= Decimal(str(tolerance)):
        return None
    listed = [{"type": item["activity_type"], "net_amount": str(item["net_amount"]), "at": str(item["activity_at"])}
              for item in activities]
    return Failure("cash", None, None, {"alpaca_cash": str(alpaca_cash), "expected_cash": str(expected_cash),
                                        "difference": str(difference), "activities": listed})
