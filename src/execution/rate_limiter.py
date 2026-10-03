"""
rate_limiter.py

Controls the total Alpaca API calls per minute to avoid hitting the rate limit
"""

from collections import deque
import time
from config.constants import (
    MAX_CALLS,
    WINDOW_SECONDS,
    RATE_LIMIT_ALERT_THRESHOLD,
    RATE_LIMIT_ALERT_COOLDOWN_SECONDS
)
import requests
from logger import api_log
from notifications import send_critical

class RateLimiter:
    def __init__(self, max_calls=MAX_CALLS, window_seconds=WINDOW_SECONDS):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.rate_deque = deque()

    def wait(self):
        while self.rate_deque and self.rate_deque[0] < (time.monotonic() - self.window_seconds):
            self.rate_deque.popleft()

        if len(self.rate_deque) >= self.max_calls:
            seconds_sleep = (self.rate_deque[0] + self.window_seconds) - time.monotonic()
            time.sleep(max(0, seconds_sleep))

        self.rate_deque.append(time.monotonic())

class RateLimitedSession(requests.Session):
    def __init__(self, limiter):
        super().__init__()
        self.limiter = limiter
        self.last_alert = None

    def request(self, *args, **kwargs):
        self.limiter.wait()
        response = super().request(*args, **kwargs)
        api_log.info(f"{response.request.method} {response.url} "
                     f"status={response.status_code} "
                     f"time={response.elapsed.total_seconds():.3f}s "
                     f"remaining={response.headers.get('X-RateLimit-Remaining')}"
                     )
        if response.headers.get('X-RateLimit-Remaining') is not None:
            remaining = int(response.headers.get('X-RateLimit-Remaining'))
            if (remaining < RATE_LIMIT_ALERT_THRESHOLD
                 and (self.last_alert is None 
                         or (time.monotonic() - self.last_alert > RATE_LIMIT_ALERT_COOLDOWN_SECONDS))):
                send_critical(f"Alpaca rate limit low: {remaining} calls left.")
                self.last_alert = time.monotonic()
        return response

