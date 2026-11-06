"""
events.py
Turn what Alpaca reports (stream messages, FILL activities, order lookups) into one TradeUpdate
"""

#Standard Library
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

#Third Party Libraries
import pandas as pd

#Local Imports
from storage.connections import to_db_time
from storage.fills import FILL_EVENT_TYPES

@dataclass(frozen=True)
class TradeUpdate:
    """One thing Alpaca reported about one order, whichever way it arrived

    Order-level fields (status, filled_quantity, filled_price) describe the whole order after this event;
    fill fields (execution_id, fill_quantity, fill_price) describe this one fill and are set only on fills.
    """
    event_type: str
    alpaca_order_id: str
    client_order_id: str | None
    ticker: str
    side: str
    order_type: str | None
    time_in_force: str | None
    status: str
    requested_quantity: int | None
    filled_quantity: int
    filled_price: Decimal | None
    event_at: datetime
    raw_json: str
    execution_id: str | None = None
    fill_quantity: int | None = None
    fill_price: Decimal | None = None

    @property
    def is_fill(self) -> bool:
        return self.event_type in FILL_EVENT_TYPES

def _decimal(value) -> Decimal | None:
    """Turn one of Alpaca's number strings into a Decimal, keeping None"""
    return None if value is None else Decimal(str(value))

def _shares(value) -> int | None:
    """Turn one of Alpaca's quantity strings ("5") into an int, keeping None"""
    return None if value is None else int(Decimal(str(value)))

def _utc(text: str) -> datetime:
    """Turn one of Alpaca's timestamps (nanoseconds, "Z") into naive UTC for the database"""
    return to_db_time(pd.Timestamp(text).floor("us"))

def from_stream(data: dict) -> TradeUpdate:
    """Read one trade-updates stream message

    Parameters:
        data (dict): The message's "data" part, e.g. {"event": "fill", "execution_id": ..., "order": {...}}

    Returns:
        A TradeUpdate with event_type = Alpaca's event ("fill", "new", "canceled", ...)
    """
    order = data["order"]
    return TradeUpdate(
        event_type=data["event"],
        alpaca_order_id=order["id"],
        client_order_id=order.get("client_order_id"),
        ticker=order["symbol"],
        side=order["side"],
        order_type=order.get("order_type") or order.get("type"),
        time_in_force=order.get("time_in_force"),
        status=order["status"],
        requested_quantity=_shares(order.get("qty")),
        filled_quantity=_shares(order.get("filled_qty")) or 0,
        filled_price=_decimal(order.get("filled_avg_price")),
        event_at=_utc(data["timestamp"]),
        raw_json=json.dumps(data),
        execution_id=data.get("execution_id"),
        fill_quantity=_shares(data.get("qty")),
        fill_price=_decimal(data.get("price")),
    )

def from_activity(activity: dict) -> TradeUpdate:
    """Read one FILL account activity, as the catch-up gets them

    The activity ID is "<timestamp>::<execution_id>", so the part after "::" is the same fill ID the stream
    sends (checked on paper Oct 30). An activity has no client_order_id, order type or average price.

    Parameters:
        activity (dict): One item from /account/activities/FILL

    Returns:
        A TradeUpdate with event_type "catch_up_fill"
    """
    filled = _shares(activity["cum_qty"])
    return TradeUpdate(
        event_type="catch_up_fill",
        alpaca_order_id=activity["order_id"],
        client_order_id=None,
        ticker=activity["symbol"],
        side="buy" if activity["side"] == "buy" else "sell",
        order_type=None,
        time_in_force=None,
        status=activity["order_status"],
        requested_quantity=filled + _shares(activity["leaves_qty"]),
        filled_quantity=filled,
        filled_price=None,
        event_at=_utc(activity["transaction_time"]),
        raw_json=json.dumps(activity),
        execution_id=activity["id"].split("::")[-1],
        fill_quantity=_shares(activity["qty"]),
        fill_price=_decimal(activity["price"]),
    )

def from_broker_order(order, ticker: str, now: datetime) -> TradeUpdate:
    """Turn an order looked up at Alpaca into a status update, as the catch-up finds them

    Parameters:
        order (BrokerOrder): Alpaca's current version of the order
        ticker (str): The order's ticker symbol (a BrokerOrder doesn't carry it)
        now (datetime): When it was looked up, naive UTC

    Returns:
        A TradeUpdate with event_type "catch_up_status" and no fill fields
    """
    return TradeUpdate(
        event_type="catch_up_status",
        alpaca_order_id=order.alpaca_order_id,
        client_order_id=order.client_order_id,
        ticker=ticker,
        side=order.side,
        order_type=order.order_type,
        time_in_force=order.time_in_force,
        status=order.status,
        requested_quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        filled_price=order.filled_price,
        event_at=now,
        raw_json=json.dumps(asdict(order), default=str),
    )

def from_saved(event_type: str, raw_json: str) -> TradeUpdate:
    """Rebuild a saved fill event from its broker_events row, for the retry pass

    Parameters:
        event_type (str): The row's event_type
        raw_json (str): The row's raw_json

    Returns:
        The same TradeUpdate the event gave when it first arrived

    Raises:
        ValueError if the row isn't a fill event
    """
    if event_type == "catch_up_fill":
        return from_activity(json.loads(raw_json))
    if event_type in FILL_EVENT_TYPES:
        return from_stream(json.loads(raw_json))
    raise ValueError(f"Can't rebuild a {event_type!r} event. Expected one of {list(FILL_EVENT_TYPES)}")
