"""
cycle.py
The shape of one trading cycle's report, and a timer that measures its length and Alpaca calls
"""

#Standard Library
from dataclasses import dataclass, field
import time

#Local Imports
from alpaca_client import api_usage as read_api_usage
from logger import health_log

MAX_CYCLE_SECONDS = 99999.99
"""The largest length health_status.cycle_seconds (DECIMAL(7,2)) can hold"""

@dataclass(frozen=True)
class CycleReport:
    """What one trading cycle did, as health_status saves it: its length in seconds (2 decimals), tickers checked,
    tickers with bad data, errors, and Alpaca calls made during it"""
    seconds: float
    tickers_checked: int
    tickers_bad: int
    errors: int
    api_calls: int

    def __post_init__(self):
        """Round seconds and refuse values the column rules would change"""
        object.__setattr__(self, "seconds", round(self.seconds, 2))
        values = self._values()
        if _clamp(values) != values:
            raise ValueError(f"Invalid cycle report {values}. {RULES}")

    def _values(self) -> dict:
        """Return the report's fields as a dict"""
        return {"seconds": self.seconds, "tickers_checked": self.tickers_checked, "tickers_bad": self.tickers_bad,
                "errors": self.errors, "api_calls": self.api_calls}

RULES = (f"Expected seconds 0 to {MAX_CYCLE_SECONDS}, counts of 0 or more, and tickers_bad at most "
         f"tickers_checked")

def _clamp(values: dict) -> dict:
    """Return the report's values moved inside the column rules (the one place those rules live)"""
    checked = max(0, values["tickers_checked"])
    return {"seconds": min(max(0.0, values["seconds"]), MAX_CYCLE_SECONDS), "tickers_checked": checked,
            "tickers_bad": min(max(0, values["tickers_bad"]), checked), "errors": max(0, values["errors"]),
            "api_calls": max(0, values["api_calls"])}

def _total_calls(clients, api_usage) -> dict:
    """Return {client index: total calls} for every client whose usage can be read"""
    totals = {}
    for index, client in enumerate(clients):
        try:
            totals[index] = api_usage(client).total_calls
        except Exception:
            continue
    return totals

@dataclass(frozen=True)
class CycleStart:
    """A running cycle: when it started and each client's call count then"""
    started: float
    clients: tuple
    calls_before: dict
    clock: object = field(repr=False)
    api_usage: object = field(repr=False)

    def finish(self, tickers_checked: int, tickers_bad: int, errors: int) -> CycleReport:
        """Return the cycle's report: its length on the clock and the calls each client made during it

        A client without a rate limiter (its usage can't be read) is left out of api_calls; the health reader logs it.
        A client whose total went down (its limiter was rebuilt) counts 0.

        Parameters:
            tickers_checked (int): Tickers the cycle looked at
            tickers_bad (int): Of those, tickers with bad data or an error
            errors (int): Errors the cycle caught and went on from

        Returns:
            A CycleReport

        Never raises: a count that can't be right (negative, more bad tickers than checked, a length that doesn't fit
        the column) is clamped and logged, so monitoring can't stop a trading cycle.
        """
        after = _total_calls(self.clients, self.api_usage)
        calls = sum(max(0, after[index] - before) for index, before in self.calls_before.items() if index in after)
        given = {"seconds": round(self.clock() - self.started, 2), "tickers_checked": tickers_checked,
                 "tickers_bad": tickers_bad, "errors": errors, "api_calls": calls}
        values = _clamp(given)
        if values != given:
            health_log.warning(f"Invalid cycle report {given}. {RULES}; saved as {values}")
        return CycleReport(**values)

def start_cycle(clients, clock=time.monotonic, api_usage=read_api_usage) -> CycleStart:
    """Start timing one trading cycle

    Parameters:
        clients (iterable): The Alpaca clients built through alpaca_client
        clock: time.monotonic (never the wall clock, so a clock change can't bend the length) or a fake
        api_usage: alpaca_client.api_usage or a fake

    Returns:
        A CycleStart; call its finish at the end of the cycle
    """
    clients = tuple(clients)
    return CycleStart(started=clock(), clients=clients, calls_before=_total_calls(clients, api_usage), clock=clock,
                      api_usage=api_usage)
