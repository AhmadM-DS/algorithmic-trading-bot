"""
test_monitoring_readers.py
Unit tests for monitoring's health readers, with a fake psutil, fake clients and a fake size reader
"""

#Standard Library
import logging
from types import SimpleNamespace

#Third Party Libraries
import pyodbc
import pytest

#Local Imports
from execution.rate_limiter import ApiUsage
from monitoring import HealthReading, start
from storage.health import database_size

class FakeSystem:
    """Stands in for psutil: each reading returns its value, or raises it when it's an exception"""
    def __init__(self, cpu=12.345, memory=40.0, disk=55.5):
        self.cpu, self.memory, self.disk = cpu, memory, disk
        self.cpu_calls = []
        self.disk_paths = []

    @staticmethod
    def _value(value):
        if isinstance(value, Exception):
            raise value
        return value

    def cpu_percent(self, interval=None):
        self.cpu_calls.append(interval)
        return self._value(self.cpu)

    def virtual_memory(self):
        return SimpleNamespace(percent=self._value(self.memory))

    def disk_usage(self, path):
        self.disk_paths.append(path)
        return SimpleNamespace(percent=self._value(self.disk))

class FakeSizes:
    """Stands in for storage's database_size: returns its pair or raises it"""
    def __init__(self, answer=(310, None)):
        self.answer = answer

    def __call__(self, conn):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

def usage_of(table):
    """Return an api_usage stand-in reading each client's ApiUsage from table, raising TypeError for unknown ones"""
    def api_usage(client):
        if client not in table:
            raise TypeError(f"{client!r} has no rate limiter")
        return table[client]
    return api_usage

def reader(system=None, sizes=None, usage=None, process="bot"):
    """Start a reader on fakes"""
    return start(process, disk_path="/", system=system or FakeSystem(), database_size=sizes or FakeSizes(),
                 api_usage=usage or usage_of({}))

def test_reading_holds_every_value_rounded_for_the_columns():
    """Read CPU, memory, disk and the database size, percentages rounded to 2 decimals"""

    reading = reader().read(conn=object(), clients=())

    assert reading == HealthReading(process="bot", cpu_pct=12.35, memory_pct=40.0, disk_pct=55.5, api_calls=0,
                                    rate_limit_remaining=None, db_used_mb=310, db_max_mb=None)

def test_start_primes_cpu_before_the_first_reading():
    """Call cpu_percent once at start, since psutil's first non-blocking call always returns 0.0"""
    system = FakeSystem()

    reader(system=system).read(conn=object(), clients=())

    assert system.cpu_calls == [None, None]

def test_disk_is_read_at_the_set_path():
    """Read disk use at the path the setting names"""
    system = FakeSystem()

    reader(system=system).read(conn=object(), clients=())

    assert system.disk_paths == ["/"]

def test_unknown_process_is_refused():
    """Refuse a process name the health tables don't allow"""
    with pytest.raises(ValueError, match="screener"):
        reader(process="screener")

@pytest.mark.parametrize("field, system", [("cpu_pct", FakeSystem(cpu=OSError("no access"))),
                                           ("memory_pct", FakeSystem(memory=RuntimeError("psutil broke"))),
                                           ("disk_pct", FakeSystem(disk=FileNotFoundError("no such path")))])
def test_failed_reading_is_none_and_the_rest_are_read(field, system):
    """Save a failed reading as None and still read every other value"""

    reading = reader(system=system).read(conn=object(), clients=())

    assert getattr(reading, field) is None
    assert reading.db_used_mb == 310

@pytest.mark.parametrize("value", [150.0, -1.0, float("nan"), "12"])
def test_percentage_that_cant_be_right_is_none(value):
    """Refuse a percentage outside 0-100 or not a number, so it never overflows DECIMAL(5,2)"""

    reading = reader(system=FakeSystem(memory=value)).read(conn=object(), clients=())

    assert reading.memory_pct is None

def test_failing_reading_is_logged_once_and_its_recovery_once(caplog):
    """Log one line when a reading starts failing and one when it works again, not one a minute"""
    system = FakeSystem(disk=OSError("unplugged"))
    health = reader(system=system)

    with caplog.at_level(logging.INFO, logger="health"):
        health.read(conn=object(), clients=())
        health.read(conn=object(), clients=())
        system.disk = 50.0
        health.read(conn=object(), clients=())

    assert caplog.text.count("disk_pct reading failed") == 1
    assert caplog.text.count("disk_pct reading works again") == 1

def test_api_calls_add_up_and_remaining_is_the_lowest():
    """Sum every client's calls in the window and keep the lowest remaining count Alpaca sent"""
    usage = usage_of({"trading": ApiUsage(calls_in_window=12, last_remaining=150, total_calls=40),
                      "data": ApiUsage(calls_in_window=30, last_remaining=9000, total_calls=99),
                      "stream": ApiUsage(calls_in_window=1, last_remaining=None, total_calls=1)})

    reading = reader(usage=usage).read(conn=object(), clients=("trading", "data", "stream"))

    assert (reading.api_calls, reading.rate_limit_remaining) == (43, 150)

def test_client_without_limiter_is_skipped_and_logged():
    """Count the other clients and log the one without a rate limiter"""
    usage = usage_of({"trading": ApiUsage(calls_in_window=5, last_remaining=170, total_calls=5)})

    reading = reader(usage=usage).read(conn=object(), clients=("trading", "bare"))

    assert (reading.api_calls, reading.rate_limit_remaining) == (5, 170)

@pytest.mark.parametrize("sizes", [FakeSizes(pyodbc.OperationalError("connection lost")),
                                   FakeSizes(pyodbc.ProgrammingError("permission denied"))])
def test_database_size_failure_is_none(sizes):
    """Save both database sizes as None when the database can't answer"""

    reading = reader(sizes=sizes).read(conn=object(), clients=())

    assert (reading.db_used_mb, reading.db_max_mb) == (None, None)

def test_no_connection_means_no_database_size():
    """Skip the size query when there's no connection (the database is down at startup)"""

    reading = reader().read(conn=None, clients=())

    assert (reading.db_used_mb, reading.db_max_mb) == (None, None)

def test_reader_never_raises():
    """Return a reading even when an unexpected error hits every reader"""
    boom = RuntimeError("bug")

    reading = reader(system=FakeSystem(boom, boom, boom), sizes=FakeSizes(boom),
                     usage=lambda client: (_ for _ in ()).throw(boom)).read(conn=object(), clients=("trading",))

    assert reading == HealthReading(process="bot", cpu_pct=None, memory_pct=None, disk_pct=None, api_calls=0,
                                    rate_limit_remaining=None, db_used_mb=None, db_max_mb=None)

class FakeSizeConn:
    """A connection whose one query returns the given used MB and max bytes"""
    def __init__(self, used_mb, max_bytes):
        self.row = SimpleNamespace(used_mb=used_mb, max_bytes=max_bytes)

    def cursor(self):
        return self

    def execute(self, sql):
        return self

    def fetchone(self):
        return self.row

@pytest.mark.parametrize("max_bytes, max_mb", [(2147483648, 2048), (None, None), (-1, None), (0, None)])
def test_database_max_is_none_when_there_is_no_real_limit(max_bytes, max_mb):
    """Turn Azure's max size into MB, and save None when the server reports no limit (Express: NULL, or -1)"""

    used, limit = database_size(FakeSizeConn(310, max_bytes))

    assert (used, limit) == (310, max_mb)

@pytest.mark.parametrize("answer", [None, (1, 2, 3)])
def test_size_reader_answer_that_isnt_a_pair_is_none(answer):
    """Save both sizes as None when the size reader returns something that isn't a pair, without raising"""

    reading = reader(sizes=FakeSizes(answer)).read(conn=object(), clients=())

    assert (reading.db_used_mb, reading.db_max_mb) == (None, None)
