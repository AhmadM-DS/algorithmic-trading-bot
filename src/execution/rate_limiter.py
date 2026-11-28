"""
rate_limiter.py
Keep Alpaca calls under the per-minute limit and count them for monitoring
"""

#Standard Library
from collections import deque
from dataclasses import dataclass
import threading
import time

#Third Party Libraries
import requests

#Local Imports
from config.constants import (
    ALPACA_TIMEOUT_SECONDS,
    MAX_CALLS,
    WINDOW_SECONDS,
    RATE_LIMIT_ALERT_THRESHOLD,
    RATE_LIMIT_ALERT_COOLDOWN_SECONDS
)
from logger import api_log
from notifications import send_critical

@dataclass(frozen=True)
class ApiUsage:
    """One client's Alpaca calls: in the last window, since it was built, and Alpaca's last remaining count"""
    calls_in_window: int
    last_remaining: int | None
    total_calls: int

class RateLimiter:
    def __init__(self, max_calls=MAX_CALLS, window_seconds=WINDOW_SECONDS, clock=time.monotonic, sleep=time.sleep):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.clock = clock
        self.sleep = sleep
        self.rate_deque = deque()
        self.total_calls = 0
        self.lock = threading.Lock()

    def _drop_old_calls(self):
        """Forget calls made more than one window ago (call with the lock held)"""
        while self.rate_deque and self.rate_deque[0] < (self.clock() - self.window_seconds):
            self.rate_deque.popleft()

    def wait(self):
        """Sleep until one more call fits in the window, then count it"""
        with self.lock:
            self._drop_old_calls()
            seconds_sleep = 0
            if len(self.rate_deque) >= self.max_calls:
                seconds_sleep = (self.rate_deque[0] + self.window_seconds) - self.clock()
        if seconds_sleep > 0:
            self.sleep(seconds_sleep)
        with self.lock:
            self.rate_deque.append(self.clock())
            self.total_calls += 1

    def calls_in_window(self) -> int:
        """Return how many calls were made in the last window, without changing the limiter

        Returns:
            The count as an int; a call exactly one window old still counts, as in wait()
        """
        with self.lock:
            cutoff = self.clock() - self.window_seconds
            return sum(1 for called in self.rate_deque if called >= cutoff)

class RateLimitedSession(requests.Session):
    def __init__(self, limiter):
        super().__init__()
        self.limiter = limiter
        self.last_alert = None
        self.last_remaining = None

    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", ALPACA_TIMEOUT_SECONDS)
        self.limiter.wait()
        response = super().request(*args, **kwargs)
        header = response.headers.get("X-RateLimit-Remaining")
        api_log.info(f"{response.request.method} {response.url} "
                     f"status={response.status_code} "
                     f"time={response.elapsed.total_seconds():.3f}s "
                     f"remaining={header}"
                     )
        if header is None:
            return response
        try:
            remaining = int(header)
        except ValueError:
            api_log.warning(f"Invalid X-RateLimit-Remaining {header!r} from {response.url}. Expected a whole number; "
                            f"kept the last count {self.last_remaining}")
            return response

        self.last_remaining = remaining
        now = self.limiter.clock()
        if (remaining < RATE_LIMIT_ALERT_THRESHOLD
                and (self.last_alert is None or now - self.last_alert > RATE_LIMIT_ALERT_COOLDOWN_SECONDS)):
            send_critical(f"Alpaca rate limit low: {remaining} calls left.")
            self.last_alert = now
        return response

    def usage(self) -> ApiUsage:
        """Return this session's call counts and Alpaca's last remaining count

        Returns:
            An ApiUsage; last_remaining is None until Alpaca has sent a readable count
        """
        return ApiUsage(calls_in_window=self.limiter.calls_in_window(),
                        last_remaining=self.last_remaining,
                        total_calls=self.limiter.total_calls)
