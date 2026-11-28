"""
test_monitoring_cycle.py
Unit tests for monitoring's CycleReport and the start_cycle / finish timer, with a fake clock and fake clients
"""

#Third Party Libraries
import pytest

#Local Imports
from execution.rate_limiter import ApiUsage
from monitoring import CycleReport, start_cycle

class FakeClock:
    """A monotonic clock the test moves by hand"""
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now

class FakeUsage:
    """Stands in for alpaca_client.api_usage: each client's total_calls from a table the test changes"""
    def __init__(self, totals):
        self.totals = totals

    def __call__(self, client):
        if client not in self.totals:
            raise TypeError(f"{client!r} has no rate limiter")
        return ApiUsage(calls_in_window=0, last_remaining=None, total_calls=self.totals[client])

def test_report_rounds_seconds_for_the_column():
    """Round the cycle's length to 2 decimals, as cycle_seconds stores it"""

    report = CycleReport(seconds=4.5678, tickers_checked=20, tickers_bad=1, errors=0, api_calls=12)

    assert report.seconds == 4.57

@pytest.mark.parametrize("fields", [{"seconds": -0.1}, {"tickers_checked": -1}, {"tickers_bad": -1},
                                    {"errors": -1}, {"api_calls": -1}, {"tickers_bad": 21},
                                    {"seconds": 100000.0}])
def test_report_refuses_values_that_cant_be_right(fields):
    """Refuse negative counts, more bad tickers than checked, and a length too big for DECIMAL(7,2)"""
    values = {"seconds": 4.0, "tickers_checked": 20, "tickers_bad": 0, "errors": 0, "api_calls": 0} | fields

    with pytest.raises(ValueError):
        CycleReport(**values)

def test_finish_measures_seconds_and_api_calls_of_the_cycle():
    """Time the cycle on the clock and count each client's calls made during it"""
    clock, usage = FakeClock(), FakeUsage({"trading": 30, "data": 5})
    cycle = start_cycle(("trading", "data"), clock=clock, api_usage=usage)
    clock.now, usage.totals = 104.567, {"trading": 40, "data": 5}

    report = cycle.finish(tickers_checked=20, tickers_bad=2, errors=1)

    assert report == CycleReport(seconds=4.57, tickers_checked=20, tickers_bad=2, errors=1, api_calls=10)

def test_client_that_cant_be_read_is_left_out_of_the_count():
    """Count only clients read both before and after, so a missing reading can't make up calls"""
    clock, usage = FakeClock(), FakeUsage({"trading": 30, "data": 5})
    cycle = start_cycle(("trading", "data", "bare"), clock=clock, api_usage=usage)
    clock.now, usage.totals = 101.0, {"trading": 31}

    report = cycle.finish(tickers_checked=1, tickers_bad=0, errors=0)

    assert report.api_calls == 1

def test_cycle_with_no_clients_made_no_calls():
    """Report 0 calls when the cycle had no Alpaca clients"""
    clock = FakeClock()
    cycle = start_cycle((), clock=clock, api_usage=FakeUsage({}))
    clock.now = 100.5

    report = cycle.finish(tickers_checked=0, tickers_bad=0, errors=0)

    assert (report.seconds, report.api_calls) == (0.5, 0)

def test_client_whose_count_restarted_adds_no_calls():
    """Count 0 for a client whose total went down (its limiter was rebuilt), instead of a negative count"""
    clock, usage = FakeClock(), FakeUsage({"trading": 30, "data": 5})
    cycle = start_cycle(("trading", "data"), clock=clock, api_usage=usage)
    clock.now, usage.totals = 101.0, {"trading": 2, "data": 8}

    report = cycle.finish(tickers_checked=1, tickers_bad=0, errors=0)

    assert report.api_calls == 3

def test_finish_never_raises_and_clamps_impossible_counts(caplog):
    """Return a clamped report and log a warning instead of stopping the trading cycle"""
    clock = FakeClock()
    cycle = start_cycle(("trading",), clock=clock, api_usage=lambda client: 1 / 0)
    clock.now = 101.0

    report = cycle.finish(tickers_checked=2, tickers_bad=5, errors=-1)

    assert report == CycleReport(seconds=1.0, tickers_checked=2, tickers_bad=2, errors=0, api_calls=0)
    assert "cycle report" in caplog.text

def test_finish_logs_nothing_for_a_good_cycle(caplog):
    """Log no warning when every count is fine"""
    clock = FakeClock()
    cycle = start_cycle((), clock=clock, api_usage=FakeUsage({}))
    clock.now = 102.0

    cycle.finish(tickers_checked=3, tickers_bad=1, errors=0)

    assert "cycle report" not in caplog.text
