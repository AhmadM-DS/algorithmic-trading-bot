"""
test_rate_limiter.py
Unit tests for execution/rate_limiter.py's counters and header reading, with a fake clock
"""

#Standard Library
from datetime import timedelta

#Third Party Libraries
import pytest
import requests

#Local Imports
from execution import rate_limiter
from execution.rate_limiter import ApiUsage, RateLimitedSession, RateLimiter

class FakeClock:
    """A monotonic clock the test moves by hand; sleeping moves it too"""
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

class FakeResponse:
    """Just enough of a requests.Response for RateLimitedSession"""
    status_code = 200
    url = "https://paper-api.alpaca.markets/v2/orders"
    elapsed = timedelta(seconds=0.1)

    class request:
        method = "GET"

    def __init__(self, headers):
        self.headers = headers

@pytest.fixture
def clock():
    """A fresh fake clock"""
    return FakeClock()

@pytest.fixture
def limiter(clock):
    """A limiter of 3 calls per 60 seconds on the fake clock"""
    return RateLimiter(max_calls=3, window_seconds=60, clock=clock, sleep=clock.sleep)

@pytest.fixture
def responses(monkeypatch):
    """Answer each request with the next headers in the list, and record critical alerts"""
    queue = []
    alerts = []

    def fake_request(self, method, url, **kwargs):
        return FakeResponse(queue.pop(0))

    monkeypatch.setattr(requests.Session, "request", fake_request)
    monkeypatch.setattr(rate_limiter, "send_critical", alerts.append)
    return queue, alerts

def make_session(limiter):
    """Return a session on the given limiter"""
    return RateLimitedSession(limiter)

def test_calls_in_window_counts_recent_calls(limiter):
    """Count every call made inside the window"""
    limiter.wait()
    limiter.wait()

    calls = limiter.calls_in_window()

    assert calls == 2

def test_calls_in_window_drops_calls_older_than_window(limiter, clock):
    """Leave out a call made more than the window ago"""
    limiter.wait()
    clock.now += 61
    limiter.wait()

    calls = limiter.calls_in_window()

    assert calls == 1

def test_calls_in_window_keeps_call_exactly_window_old(limiter, clock):
    """Still count a call exactly one window old, the same way wait() does"""
    limiter.wait()
    clock.now += 60

    calls = limiter.calls_in_window()

    assert calls == 1

def test_calls_in_window_is_zero_before_any_call(limiter):
    """Report no calls for a limiter that hasn't been used"""

    calls = limiter.calls_in_window()

    assert calls == 0

def test_total_calls_keeps_counting_past_window(limiter, clock):
    """Count every call since the limiter was made, also those outside the window"""
    limiter.wait()
    clock.now += 120
    limiter.wait()

    total = limiter.total_calls

    assert total == 2

def test_wait_sleeps_until_oldest_call_leaves_window(limiter, clock):
    """Sleep only as long as it takes the oldest call to leave a full window"""
    limiter.wait()
    clock.now += 10
    limiter.wait()
    limiter.wait()

    limiter.wait()

    assert clock.slept == [pytest.approx(50)]

def test_session_remaining_is_none_before_any_call(limiter):
    """Report no remaining count before Alpaca has answered once"""
    session = make_session(limiter)

    usage = session.usage()

    assert usage == ApiUsage(calls_in_window=0, last_remaining=None, total_calls=0)

def test_session_saves_last_remaining_header(limiter, responses):
    """Keep the remaining count from Alpaca's latest answer"""
    queue, alerts = responses
    queue.extend([{"X-RateLimit-Remaining": "150"}, {"X-RateLimit-Remaining": "149"}])
    session = make_session(limiter)
    session.request("GET", "https://paper-api.alpaca.markets/v2/clock")

    session.request("GET", "https://paper-api.alpaca.markets/v2/clock")

    assert session.usage() == ApiUsage(calls_in_window=2, last_remaining=149, total_calls=2)

def test_session_keeps_last_remaining_when_header_missing(limiter, responses):
    """Keep the last remaining count when an answer has no header"""
    queue, alerts = responses
    queue.extend([{"X-RateLimit-Remaining": "150"}, {}])
    session = make_session(limiter)
    session.request("GET", "https://paper-api.alpaca.markets/v2/clock")

    session.request("GET", "https://paper-api.alpaca.markets/v2/clock")

    assert session.usage().last_remaining == 150

@pytest.mark.parametrize("header", ["abc", "", "12.5"])
def test_session_ignores_malformed_remaining_header(limiter, responses, header):
    """Return Alpaca's answer and keep the last count when the remaining header isn't a whole number"""
    queue, alerts = responses
    queue.extend([{"X-RateLimit-Remaining": "150"}, {"X-RateLimit-Remaining": header}])
    session = make_session(limiter)
    session.request("GET", "https://paper-api.alpaca.markets/v2/clock")

    response = session.request("GET", "https://paper-api.alpaca.markets/v2/clock")

    assert response.headers == {"X-RateLimit-Remaining": header}
    assert session.usage().last_remaining == 150
    assert alerts == []

def test_session_alerts_when_remaining_low(limiter, responses):
    """Send one critical alert when the remaining count drops below the threshold"""
    queue, alerts = responses
    queue.append({"X-RateLimit-Remaining": "5"})
    session = make_session(limiter)

    session.request("GET", "https://paper-api.alpaca.markets/v2/clock")

    assert len(alerts) == 1
    assert "5 calls left" in alerts[0]

def test_counting_calls_doesnt_change_the_limiter(limiter, clock):
    """Count calls without removing any, so a monitoring read can't race an order's wait()"""
    limiter.wait()
    clock.now += 61

    calls = limiter.calls_in_window()

    assert (calls, len(limiter.rate_deque)) == (0, 1)
