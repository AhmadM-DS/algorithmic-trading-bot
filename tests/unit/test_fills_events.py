"""
test_fills_events.py
Unit tests for fills.events: real paper messages (Oct 30) turned into TradeUpdates
"""

#Standard Library
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

#Third Party Libraries
import pytest

#Local Imports
from execution.broker import BrokerOrder
from fills.events import from_activity, from_broker_order, from_saved, from_stream

PAPER_RUN = json.loads((Path(__file__).parent.parent / "fixtures" / "stream_events_paper.json").read_text("utf-8"))
STREAM = PAPER_RUN["stream"]
ACTIVITIES = PAPER_RUN["activities"]
BUY_FILL = next(m for m in STREAM if m["event"] == "fill" and m["order"]["side"] == "buy")
HELD_STOP = next(m for m in STREAM if m["event"] == "held" and m["order"]["order_type"] == "stop")
BUY_NEW = next(m for m in STREAM if m["event"] == "new" and m["order"]["side"] == "buy")
BUY_ACTIVITY = next(a for a in ACTIVITIES if a["side"] == "buy")

def test_stream_fill_is_read_with_its_fill_fields():
    """Read the buy fill's order, this fill's quantity / price / ID, and Alpaca's time as naive UTC"""

    update = from_stream(BUY_FILL)

    assert (update.event_type, update.is_fill, update.ticker, update.side, update.status) == \
           ("fill", True, "SPY", "buy", "filled")
    assert (update.alpaca_order_id, update.client_order_id) == \
           ("e5d8e23c-dbb7-46aa-ad84-36e1b068307a", "paper_check-SPY-buy-20261030T174219Z-d306")
    assert (update.fill_quantity, update.fill_price, update.execution_id) == \
           (1, Decimal("755.22"), "7f050d7a-f9cc-409b-b8e4-09a751a8ac45")
    assert (update.requested_quantity, update.filled_quantity, update.filled_price) == (1, 1, Decimal("755.22"))
    assert update.event_at == datetime(2026, 10, 30, 17, 42, 20, 960320)

def test_stream_keeps_the_whole_message_as_raw_json():
    """Keep every field Alpaca sent, including ones the bot doesn't use yet"""

    update = from_stream(BUY_FILL)

    assert json.loads(update.raw_json) == BUY_FILL

def test_held_leg_has_no_fill_fields():
    """Read a held stop leg as a status event with no fill"""

    update = from_stream(HELD_STOP)

    assert (update.event_type, update.is_fill, update.order_type, update.status) == ("held", False, "stop", "held")
    assert (update.execution_id, update.fill_quantity, update.fill_price) == (None, None, None)

def test_new_event_carries_an_execution_id_but_is_not_a_fill():
    """Treat execution_id as a fill ID only on fill events (non-fill events carry one too)"""

    update = from_stream(BUY_NEW)

    assert update.execution_id is not None
    assert update.is_fill is False

def test_activity_fill_id_matches_the_stream_execution_id():
    """Take the part after '::' of the activity ID, which is the stream's execution_id for the same fill"""

    update = from_activity(BUY_ACTIVITY)

    assert update.execution_id == from_stream(BUY_FILL).execution_id

def test_activity_is_read_as_a_catch_up_fill():
    """Read a FILL activity's order ID, fill, cumulative quantity and requested quantity (filled + left)"""

    update = from_activity(BUY_ACTIVITY)

    assert (update.event_type, update.is_fill, update.alpaca_order_id, update.client_order_id) == \
           ("catch_up_fill", True, "e5d8e23c-dbb7-46aa-ad84-36e1b068307a", None)
    assert (update.fill_quantity, update.fill_price, update.filled_quantity, update.requested_quantity) == \
           (1, Decimal("755.22"), 1, 1)
    assert update.event_at == datetime(2026, 10, 30, 17, 42, 20, 960321)

def test_short_sale_activity_is_read_as_a_sell():
    """Read Alpaca's "sell_short" side as a sell"""

    update = from_activity({**BUY_ACTIVITY, "side": "sell_short"})

    assert update.side == "sell"

@pytest.mark.parametrize("event_type, raw", [("fill", BUY_FILL), ("catch_up_fill", BUY_ACTIVITY)])
def test_saved_fill_is_rebuilt_unchanged(event_type, raw):
    """Rebuild a fill from its broker_events row exactly as it first arrived"""
    first = from_stream(raw) if event_type == "fill" else from_activity(raw)

    rebuilt = from_saved(event_type, first.raw_json)

    assert rebuilt == first

def test_saved_non_fill_cannot_be_rebuilt():
    """Refuse to rebuild an event the retry pass never handles"""

    with pytest.raises(ValueError, match="'new'"):
        from_saved("new", json.dumps(BUY_NEW))

def test_broker_order_becomes_a_status_update():
    """Turn a looked-up order into a catch_up_status update with no fill"""
    order = BrokerOrder("alpaca-stop", "leg-coid", "sell", "stop", "day", "canceled", 1, 0, None,
                        Decimal("740.13"), None)

    update = from_broker_order(order, "SPY", datetime(2026, 10, 30, 18, 0))

    assert (update.event_type, update.status, update.ticker, update.is_fill, update.order_type) == \
           ("catch_up_status", "canceled", "SPY", False, "stop")
    assert json.loads(update.raw_json)["stop_price"] == "740.13"
