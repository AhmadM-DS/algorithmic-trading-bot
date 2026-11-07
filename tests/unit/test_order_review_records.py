"""
test_order_review_records.py
Unit tests for the pre-order review's log line and sell alert (saving and the price outage alert are
integration tests)
"""

#Standard Library
import logging

#Local Imports
from order_review import OpenOrder, review_order
from tests.unit.test_order_review_contract import _context, _facts, _request
from order_review.records import log_review

def test_price_skip_logs_the_numbers(caplog):
    """Log a moved price with the signal price, the check price, the move, its limit and the age"""
    request, facts = _request(), _facts(price=10.2)
    review = review_order(request, _context(), facts)

    with caplog.at_level(logging.INFO, logger="trades"):
        line = log_review(request, review, facts, "momentum", alert=lambda message: None)

    assert line == "price_moved: momentum buy AAPL: signal $10.00, now $10.20 (+2.0%, limit 1.0%, 10 s old, limit 120 s)"
    assert line in caplog.text

def test_missing_price_logs_that_there_was_no_trade():
    request, facts = _request(), _facts(price=None)

    line = log_review(request, review_order(request, _context(), facts), facts, "momentum", alert=lambda m: None)

    assert line == "stale_price: momentum buy AAPL: signal $10.00, no iex trade to check against"

def test_risk_only_skip_isnt_logged_here():
    """Leave risk's skips to risk (saved silently); only the order checks' skips get this line"""
    request, facts = _request(), _facts()

    assert log_review(request, review_order(request, _context(kill_switch=True), facts), facts, "momentum") is None

def test_sell_skipped_while_closed_alerts():
    """Alert when a sell can't go out because the market is closed: a day position could stay overnight"""
    sent = []
    request, facts = _request(side="sell"), _facts(session=(None, None))

    log_review(request, review_order(request, _context(held=5), facts), facts, "momentum", alert=sent.append)

    assert len(sent) == 1 and "AAPL" in sent[0]

def test_second_sell_is_only_logged():
    """Don't alert on a sell skipped because one is already out (normal when E3 sold first)"""
    sent = []
    request = _request(side="sell")
    facts = _facts(orders=[OpenOrder(3, "AAPL", "sell")])

    line = log_review(request, review_order(request, _context(held=5), facts), facts, "momentum", alert=sent.append)

    assert (line, sent) == ("open_order: momentum sell AAPL", [])
