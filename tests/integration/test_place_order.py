"""
test_place_order.py
Integration tests for execution.place_order: a FakeBroker stands in for Alpaca, rows go to noctis_test
"""

#Standard Library
from datetime import date, datetime, timedelta
from decimal import Decimal

#Third Party Libraries
import pytest

#Local Imports
from execution import OrderRequest, place_order, settle_stuck_orders
from execution.broker import BrokerOrder, BrokerUnavailable, DuplicateOrder, OrderRejected
from storage.watchlist import get_or_create_ticker

NOW = datetime(2026, 10, 28, 14, 30, 5)
WAITS = [1, 2, 4]

class CommitCounter:
    """Wraps the test connection: counts commits instead of making them, so each test still rolls back"""

    def __init__(self, conn):
        self._conn = conn
        self.commits = 0

    def commit(self):
        self.commits += 1

    def __getattr__(self, name):
        return getattr(self._conn, name)

class FakeBroker:
    """Stands in for AlpacaBroker: answers each send and lookup from a script, and records every call"""

    def __init__(self, conn, sends=(), lookups=()):
        self.conn = conn
        self.sends = list(sends)
        self.lookups = list(lookups)
        self.calls = []

    @staticmethod
    def _answer(script):
        outcome = script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def submit_bracket_buy(self, client_order_id, ticker, quantity, time_in_force, stop_price, target_price):
        self.calls.append(("buy", client_order_id, ticker, quantity, time_in_force, stop_price, target_price,
                           self.conn.commits))
        return self._answer(self.sends)

    def submit_market_sell(self, client_order_id, ticker, quantity, time_in_force):
        self.calls.append(("sell", client_order_id, ticker, quantity, time_in_force, self.conn.commits))
        return self._answer(self.sends)

    def find_order(self, client_order_id):
        self.calls.append(("find", client_order_id))
        return self._answer(self.lookups)

def accepted_buy(status="accepted", time_in_force="day"):
    """Return Alpaca's answer to a bracket buy, with its two held legs"""
    target = BrokerOrder("alpaca-target", "alpaca-made-target", "sell", "limit", time_in_force, "held", 10, 0,
                         None, None, Decimal("5.20"))
    stop = BrokerOrder("alpaca-stop", "alpaca-made-stop", "sell", "stop", time_in_force, "held", 10, 0,
                       None, Decimal("4.90"), None)
    return BrokerOrder("alpaca-buy", "ignored", "buy", "market", time_in_force, status, 10, 0, None, None, None,
                       (target, stop))

@pytest.fixture
def conn(bot_conn):
    """The bot connection, with commits counted instead of made"""
    return CommitCounter(bot_conn)

@pytest.fixture
def alerts(monkeypatch):
    """Capture Discord critical alerts instead of sending them"""
    sent = []
    monkeypatch.setattr("execution.orders.send_critical", sent.append)
    return sent

def buy_request(conn, **overrides):
    """Return a day buy of 10 AAPL at $5.00 with stop $4.90 and target $5.20"""
    strategy_id = conn.execute("SELECT strategy_id FROM strategies WHERE strategy = 'manual'").fetchone()[0]
    values = {"strategy": "momentum", "strategy_id": strategy_id, "ticker": "AAPL",
              "ticker_id": get_or_create_ticker(conn, "AAPL", date(2026, 10, 28)), "side": "buy", "quantity": 10,
              "holding_type": "day", "price": Decimal("5.00"), "stop_price": Decimal("4.90"),
              "target_price": Decimal("5.20")}
    values.update(overrides)
    return OrderRequest(**values)

def place(conn, broker, request, sleeps=None):
    """Call place_order with a fixed time and no real waiting"""
    return place_order(request, conn, broker, now=NOW, waits=WAITS,
                       sleep=(sleeps if sleeps is not None else []).append)

def rows(conn):
    """Return every orders row, oldest first"""
    return conn.execute("SELECT * FROM orders ORDER BY order_id").fetchall()

def test_accepted_buy_saves_order_and_both_legs(conn, alerts):
    """Save the buy with Alpaca's ID and status, plus each leg linked to it"""
    broker = FakeBroker(conn, sends=[accepted_buy()])

    result = place(conn, broker, buy_request(conn))

    buy, target, stop = rows(conn)
    assert (result.status, result.order_id, result.alpaca_order_id) == ("accepted", buy.order_id, "alpaca-buy")
    assert (buy.client_order_id, buy.alpaca_order_id, buy.status, buy.order_type, buy.time_in_force) == \
           (result.client_order_id, "alpaca-buy", "accepted", "market", "day")
    assert (buy.requested_quantity, buy.request_price, buy.submitted_at, buy.parent_order_id) == \
           (10, Decimal("5.00"), NOW, None)
    assert [(leg.order_type, leg.side, leg.status, leg.request_price, leg.parent_order_id, leg.alpaca_order_id)
            for leg in (target, stop)] == [("limit", "sell", "held", Decimal("5.20"), buy.order_id, "alpaca-target"),
                                           ("stop", "sell", "held", Decimal("4.90"), buy.order_id, "alpaca-stop")]
    assert alerts == []

def test_row_is_committed_before_sending(conn, alerts):
    """Commit the 'submitting' row before Alpaca is called, then commit Alpaca's answer"""
    broker = FakeBroker(conn, sends=[accepted_buy()])

    place(conn, broker, buy_request(conn))

    commits_when_sent = broker.calls[0][-1]
    assert (commits_when_sent, conn.commits) == (1, 2)

def test_buy_sends_rounded_exit_prices(conn, alerts):
    """Round the strategy's stop and target to Alpaca's ticks before sending"""
    broker = FakeBroker(conn, sends=[accepted_buy()])

    place(conn, broker, buy_request(conn, stop_price=4.9049, target_price=5.2051))

    assert broker.calls[0][5:7] == (Decimal("4.90"), Decimal("5.21"))

def test_holding_type_picks_time_in_force(conn, alerts):
    """Send a swing buy as GTC and save it that way"""
    broker = FakeBroker(conn, sends=[accepted_buy(time_in_force="gtc")])

    place(conn, broker, buy_request(conn, holding_type="swing"))

    assert (broker.calls[0][4], rows(conn)[0].time_in_force) == ("gtc", "gtc")

def test_sell_is_a_plain_market_order(conn, alerts):
    """Send a sell without legs and save one row"""
    answer = BrokerOrder("alpaca-sell", "ignored", "sell", "market", "day", "accepted", 10, 0, None, None, None)
    broker = FakeBroker(conn, sends=[answer])

    result = place(conn, broker, buy_request(conn, side="sell", stop_price=None, target_price=None))

    assert broker.calls[0][0] == "sell"
    assert (result.status, len(rows(conn)), rows(conn)[0].side) == ("accepted", 1, "sell")

def test_invalid_exit_prices_skip_without_saving_or_sending(conn, alerts):
    """Skip a buy whose stop isn't below the price, before anything is saved or sent"""
    broker = FakeBroker(conn)

    result = place(conn, broker, buy_request(conn, stop_price=Decimal("5.00")))

    assert (result.status, result.skip_reason, result.order_id) == ("skipped", "invalid_exit_prices", None)
    assert (rows(conn), broker.calls, conn.commits) == ([], [], 0)

def test_rejection_is_saved_alerted_and_never_retried(conn, alerts):
    """Save Alpaca's reason, send one alert, and don't try again"""
    broker = FakeBroker(conn, sends=[OrderRejected("insufficient buying power")])
    sleeps = []

    result = place(conn, broker, buy_request(conn), sleeps)

    row = rows(conn)[0]
    assert (result.status, result.reject_reason) == ("rejected", "insufficient buying power")
    assert (row.status, row.reject_reason, row.alpaca_order_id) == ("rejected", "insufficient buying power", None)
    assert (len(broker.calls), sleeps, len(alerts)) == (1, [], 1)
    assert "insufficient buying power" in alerts[0]

def test_no_answer_then_not_found_resends_with_same_id(conn, alerts):
    """After a timeout, look the order up; if Alpaca doesn't have it, send again with the same ID"""
    broker = FakeBroker(conn, sends=[BrokerUnavailable("read timed out"), accepted_buy()], lookups=[None])
    sleeps = []

    result = place(conn, broker, buy_request(conn), sleeps)

    first, lookup, second = broker.calls
    assert (first[0], lookup[0], second[0]) == ("buy", "find", "buy")
    assert first[1] == lookup[1] == second[1] == result.client_order_id
    assert (result.status, sleeps) == ("accepted", [1])

def test_no_answer_but_order_exists_is_kept_not_resent(conn, alerts):
    """After a timeout, keep the order Alpaca already has instead of sending a second one"""
    broker = FakeBroker(conn, sends=[BrokerUnavailable("read timed out")], lookups=[accepted_buy()])

    result = place(conn, broker, buy_request(conn))

    assert [call[0] for call in broker.calls] == ["buy", "find"]
    assert (result.status, result.alpaca_order_id, len(rows(conn))) == ("accepted", "alpaca-buy", 3)

def test_failed_lookup_still_resends_with_same_id(conn, alerts):
    """Resend with the same ID when the lookup itself fails; Alpaca refuses a real duplicate"""
    broker = FakeBroker(conn, sends=[BrokerUnavailable("timeout"), accepted_buy()],
                        lookups=[BrokerUnavailable("timeout")])

    result = place(conn, broker, buy_request(conn))

    assert [call[0] for call in broker.calls] == ["buy", "find", "buy"]
    assert result.status == "accepted"

def test_duplicate_on_retry_keeps_the_existing_order(conn, alerts):
    """Treat Alpaca refusing a repeated ID as proof the first send got through, and keep that order"""
    broker = FakeBroker(conn, sends=[BrokerUnavailable("timeout"), DuplicateOrder("client_order_id must be unique")],
                        lookups=[BrokerUnavailable("timeout"), accepted_buy()])

    result = place(conn, broker, buy_request(conn))

    assert [call[0] for call in broker.calls] == ["buy", "find", "buy", "find"]
    assert (result.status, result.alpaca_order_id, alerts) == ("accepted", "alpaca-buy", [])

def test_rejected_retry_keeps_an_earlier_send_that_got_through(conn, alerts):
    """Keep the order when a retry is refused because the earlier send already used the buying power"""
    broker = FakeBroker(conn, sends=[BrokerUnavailable("timeout"), OrderRejected("insufficient buying power")],
                        lookups=[None, accepted_buy()])

    result = place(conn, broker, buy_request(conn))

    assert (result.status, rows(conn)[0].status, alerts) == ("accepted", "accepted", [])

def test_every_try_failing_marks_unknown_and_alerts(conn, alerts):
    """After the last retry, save status unknown and send one alert"""
    broker = FakeBroker(conn, sends=[BrokerUnavailable("timeout")] * 4, lookups=[None] * 3)
    sleeps = []

    result = place(conn, broker, buy_request(conn), sleeps)

    assert (result.status, rows(conn)[0].status, rows(conn)[0].alpaca_order_id) == ("unknown", "unknown", None)
    assert (sleeps, sum(call[0] == "buy" for call in broker.calls), len(alerts)) == (WAITS, 4, 1)

def unknown_order(conn, alerts):
    """Place a buy that gets no answer at all, leaving it unknown, and return its order_id"""
    broker = FakeBroker(conn, sends=[BrokerUnavailable("timeout")] * 4, lookups=[None] * 3)
    order_id = place(conn, broker, buy_request(conn)).order_id
    alerts.clear()
    return order_id

def submitting_order(conn, saved_at=NOW):
    """Save a buy row the way place_order does just before sending, and return its order_id"""
    request = buy_request(conn)
    return conn.execute(
        "INSERT INTO orders (client_order_id, side, requested_quantity, order_type, time_in_force, submitted_at, "
        "[status], strategy_id, ticker_id) OUTPUT INSERTED.order_id "
        "VALUES (?, 'buy', 10, 'market', 'day', ?, 'submitting', ?, ?)",
        (f"momentum-AAPL-buy-stuck-{saved_at:%H%M%S}", saved_at, request.strategy_id, request.ticker_id),
    ).fetchone()[0]

def settle(conn, broker, minutes_later=2):
    """Run the sweep a few minutes after NOW"""
    return settle_stuck_orders(conn, broker, now=NOW + timedelta(minutes=minutes_later))

def test_unknown_order_alpaca_has_is_saved_with_legs(conn, alerts):
    """Copy Alpaca's version and the legs onto an unknown order, and close its alert"""
    order_id = unknown_order(conn, alerts)
    broker = FakeBroker(conn, lookups=[accepted_buy(status="filled")])

    settled = settle(conn, broker)

    buy, target, stop = rows(conn)
    assert settled == [(order_id, "filled")]
    assert (buy.status, buy.alpaca_order_id, target.parent_order_id, stop.parent_order_id) == \
           ("filled", "alpaca-buy", order_id, order_id)
    assert (target.strategy_id, target.ticker_id) == (buy.strategy_id, buy.ticker_id)
    assert len(alerts) == 1 and "settled" in alerts[0]

def test_submitting_order_alpaca_never_got_is_not_sent(conn, alerts):
    """Mark a row Alpaca has no order for as not_sent, without an alert"""
    order_id = submitting_order(conn)
    broker = FakeBroker(conn, lookups=[None])

    settled = settle(conn, broker)

    assert (settled, rows(conn)[0].status, alerts, conn.commits) == ([(order_id, "not_sent")], "not_sent", [], 1)

def test_failed_lookup_leaves_order_for_next_cycle(conn, alerts):
    """Leave the row as it is when Alpaca can't be asked"""
    submitting_order(conn)
    broker = FakeBroker(conn, lookups=[BrokerUnavailable("timeout")])

    settled = settle(conn, broker)

    assert (settled, rows(conn)[0].status, conn.commits) == ([], "submitting", 0)

def test_recent_order_is_not_touched(conn, alerts):
    """Skip rows younger than the stuck limit; place_order may still be retrying them"""
    submitting_order(conn)
    broker = FakeBroker(conn)

    settled = settle(conn, broker, minutes_later=0.5)

    assert (settled, broker.calls) == ([], [])

def test_every_stuck_order_is_settled_oldest_first(conn, alerts):
    """Settle each stuck row in one sweep, in the order they were saved"""
    first = submitting_order(conn, saved_at=NOW - timedelta(minutes=5))
    second = submitting_order(conn)
    broker = FakeBroker(conn, lookups=[None, None])

    settled = settle(conn, broker)

    assert settled == [(first, "not_sent"), (second, "not_sent")]
