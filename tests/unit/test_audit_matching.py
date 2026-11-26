"""
test_audit_matching.py
Unit tests for the end-of-day audit's pure parts: reading activities, matching fills, the cash check
"""

#Standard Library
from datetime import date, datetime
from decimal import Decimal

#Third Party Libraries
import pytest

#Local Imports
from audit.matching import (Fill, activity_record, alpaca_fill, cash_failure, day_window, is_fill_activity,
                            match_fills)

FILL_ACTIVITY = {"id": "20261124143005123::7f050d7a-aaaa", "activity_type": "FILL", "transaction_time":
                 "2026-11-24T14:30:05.123456789Z", "type": "fill", "price": "4.12", "qty": "50", "side": "buy",
                 "symbol": "ABC", "leaves_qty": "0", "order_id": "order-1", "cum_qty": "50", "order_status": "filled"}
FEE_ACTIVITY = {"id": "20261124000000000::fee-1", "activity_type": "FEE", "date": "2026-11-24",
                "net_amount": "-0.02", "description": "TAF fee", "status": "executed"}

def fill(fill_id="f1", ticker="ABC", side="buy", quantity="50", price="4.12") -> Fill:
    """Return a Fill with the given values"""
    return Fill(fill_id, ticker, side, Decimal(quantity), Decimal(price))

def test_day_window_is_new_york_midnight_to_midnight_in_utc():
    """Cover one New York trading day in naive UTC (EST: midnight is 05:00 UTC)"""

    start, end = day_window(date(2026, 11, 24))

    assert (start, end) == (datetime(2026, 11, 24, 5), datetime(2026, 11, 25, 5))

def test_day_window_follows_daylight_saving():
    """Use 04:00 UTC for midnight in summer (EDT)"""

    assert day_window(date(2026, 7, 1))[0] == datetime(2026, 7, 1, 4)

def test_fill_activity_record_keeps_alpacas_values():
    """Save a FILL with its time, ticker, side, quantity and price, and the whole message raw"""

    record = activity_record(FILL_ACTIVITY)

    assert (record["alpaca_activity_id"], record["alpaca_order_id"], record["activity_type"], record["activity_at"],
            record["ticker"], record["side"], record["quantity"], record["price"], record["net_amount"]) == (
        FILL_ACTIVITY["id"], "order-1", "FILL", datetime(2026, 11, 24, 14, 30, 5, 123456), "ABC", "buy",
        Decimal("50"), Decimal("4.12"), None)
    assert '"symbol": "ABC"' in record["raw_json"]

def test_dated_activity_record_is_stamped_at_new_york_midnight():
    """Stamp an activity that has only a date (a fee) at the start of that New York day"""

    record = activity_record(FEE_ACTIVITY)

    assert (record["activity_type"], record["activity_at"], record["net_amount"], record["ticker"]) == (
        "FEE", datetime(2026, 11, 24, 5), Decimal("-0.02"), None)

def test_short_sale_side_is_saved_as_sell():
    """Fit Alpaca's "sell_short" into the side column as a sell (the raw JSON keeps the original)"""

    record = activity_record({**FILL_ACTIVITY, "side": "sell_short"})

    assert record["side"] == "sell"

def test_fill_activities_are_told_apart_from_others():
    """Tell a FILL activity from a fee"""
    assert (is_fill_activity(FILL_ACTIVITY), is_fill_activity(FEE_ACTIVITY)) == (True, False)

def test_alpaca_fill_uses_the_execution_id_after_the_timestamp():
    """Match on the part of the activity ID after "::", the same ID the stream sends"""

    assert alpaca_fill(FILL_ACTIVITY) == fill(fill_id="7f050d7a-aaaa")

def test_matching_fills_find_nothing_wrong():
    """Report nothing when every fill is on both sides with the same numbers"""

    result = match_fills([fill()], [fill(price="4.1200")])

    assert result.failures() == []

def test_fill_only_at_alpaca_is_missing_in_db():
    """Report a fill Alpaca lists that the database doesn't have"""
    result = match_fills([fill(), fill("f2", ticker="XYZ")], [fill()])

    assert [(f.kind, f.ticker, f.fill_id) for f in result.failures()] == [("missing_in_db", "XYZ", "f2")]

def test_fill_only_in_db_is_missing_at_alpaca():
    """Report a trade the database has that Alpaca doesn't list"""
    result = match_fills([], [fill()])

    assert [(f.kind, f.ticker, f.fill_id) for f in result.failures()] == [("missing_at_alpaca", "ABC", "f1")]

@pytest.mark.parametrize("alpaca_price, database_price, mismatched", [
    ("4.12", "4.13", True),
    ("0.12345", "0.1235", False),
    ("0.12344", "0.1235", True),
])
def test_prices_are_compared_after_rounding_to_four_decimals(alpaca_price, database_price, mismatched):
    """Compare prices at the database's 4 decimals, so only a real difference counts"""

    result = match_fills([fill(price=alpaca_price)], [fill(price=database_price)])

    assert (len(result.price_mismatches) == 1) is mismatched

def test_different_quantity_or_side_is_a_quantity_mismatch():
    """Count a different share count, or the same count on the other side, as a quantity mismatch"""

    result = match_fills([fill(), fill("f2")], [fill(quantity="40"), fill("f2", side="sell")])

    assert [(f.kind, f.fill_id) for f in result.failures()] == [("quantity_mismatch", "f1"),
                                                                ("quantity_mismatch", "f2")]

def test_mismatch_details_hold_both_sides():
    """Keep Alpaca's and the database's numbers in the failure's details"""

    failure = match_fills([fill(price="4.12")], [fill(price="4.20")]).failures()[0]

    assert failure.details == {"alpaca": {"side": "buy", "quantity": "50", "price": "4.12"},
                               "database": {"side": "buy", "quantity": "50", "price": "4.20"}}

def test_cash_within_tolerance_passes():
    """Pass a difference smaller than the tolerance (rounding)"""
    assert cash_failure(Decimal("900.00"), Decimal("900.005"), 0.01, []) is None

def test_cash_outside_tolerance_is_a_cash_failure_listing_the_days_activities():
    """Fail the cash check with both numbers, the difference and the day's non-fill activities"""
    activities = [{"activity_type": "FEE", "net_amount": Decimal("-0.02"), "activity_at": datetime(2026, 11, 24, 5)}]

    failure = cash_failure(Decimal("900.00"), Decimal("905.00"), 0.01, activities)

    assert (failure.kind, failure.ticker) == ("cash", None)
    assert failure.details == {"alpaca_cash": "900.00", "expected_cash": "905.00", "difference": "-5.00",
                               "activities": [{"type": "FEE", "net_amount": "-0.02", "at": "2026-11-24 05:00:00"}]}

def test_symbol_longer_than_the_column_is_saved_without_a_ticker():
    """Keep an option symbol out of the 10-character ticker column (the raw JSON keeps it) instead of failing"""

    record = activity_record({**FILL_ACTIVITY, "symbol": "SPY261218C00600000"})

    assert record["ticker"] is None and "SPY261218C00600000" in record["raw_json"]

def test_cash_exactly_at_the_tolerance_passes():
    """Pass a difference equal to CASH_TOLERANCE: only a larger one is a failure"""

    assert cash_failure(Decimal("900.00"), Decimal("900.01"), 0.01, []) is None

@pytest.mark.parametrize("change", [{"activity_type": "DIVCGLTAXES"}, {"id": "x" * 129},
                                    {"order_id": "o" * 129}, {"net_amount": "1" + "0" * 15},
                                    {"qty": "-1" + "0" * 15}])
def test_activity_too_big_for_its_columns_is_refused(change):
    """Refuse an activity a column can't hold (type over 10 characters, IDs over 128, numbers of 10^15 or more), so
    it becomes an unreadable_activity failure instead of a database error"""
    activity = {"id": "20261124000000000::fee-1", "activity_type": "FEE", "date": "2026-11-24", "net_amount": "-0.02",
                **change}

    with pytest.raises(ValueError, match="too"):
        activity_record(activity)
