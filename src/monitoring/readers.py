"""
readers.py
Read one heartbeat's health values: CPU, memory, disk, Alpaca API use and the database size
"""

#Standard Library
from dataclasses import dataclass
import math

#Third Party Libraries
import psutil

#Local Imports
from alpaca_client import api_usage as read_api_usage
from config.constants import HEALTH_DISK_PATH, PROCESSES
from logger import ChangeLog, health_log
from storage.health import database_size as read_database_size

@dataclass(frozen=True)
class HealthReading:
    """One heartbeat's values for health_status; a reading that failed is None (api_calls is 0 when idle)"""
    process: str
    cpu_pct: float | None
    memory_pct: float | None
    disk_pct: float | None
    api_calls: int
    rate_limit_remaining: int | None
    db_used_mb: int | None
    db_max_mb: int | None

def _percent(value) -> float:
    """Return a percentage rounded for DECIMAL(5,2), or raise ValueError for one that can't be right"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not 0 <= value <= 100:
        raise ValueError(f"Invalid percentage {value!r}. Expected a number from 0 to 100")
    return round(float(value), 2)

def _pair(sizes) -> tuple:
    """Return the size reader's (used_mb, max_mb), or raise TypeError for anything that isn't a pair"""
    if not isinstance(sizes, tuple) or len(sizes) != 2:
        raise TypeError(f"Invalid database size {sizes!r}. Expected (used_mb, max_mb)")
    return sizes

class HealthReader:
    """Reads one process's health; each reading fails on its own (None) and is logged once when it starts failing
    and once when it works again. read never raises
    """
    def __init__(self, process: str, disk_path: str, system, database_size, api_usage):
        if process not in PROCESSES:
            raise ValueError(f"Unknown process {process!r}. Expected one of {list(PROCESSES)}")
        self.process = process
        self.disk_path = disk_path
        self.system = system
        self.database_size = database_size
        self.api_usage = api_usage
        self.failing = ChangeLog(health_log)

    def _try(self, name: str, read, failed=None):
        """Return read(), or failed when it raises, logging the change of state once"""
        try:
            value = read()
        except Exception as error:
            self.failing.failed(name, f"{name} reading failed ({type(error).__name__}: {error}); saved as empty "
                                      f"until it works again")
            return failed
        self.failing.recovered(name, f"{name} reading works again")
        return value

    def read(self, conn, clients) -> HealthReading:
        """Read every value for one heartbeat

        Parameters:
            conn (Connection | None): An open database connection; None skips the size (database down)
            clients (iterable): The Alpaca clients built through alpaca_client

        Returns:
            A HealthReading
        """
        calls, remaining = 0, []
        for index, client in enumerate(clients):
            usage = self._try(f"api_usage[{index}]", lambda: self.api_usage(client))
            if usage is not None:
                calls += usage.calls_in_window
                if usage.last_remaining is not None:
                    remaining.append(usage.last_remaining)
        if conn is None:
            used_mb, max_mb = None, None
        else:
            used_mb, max_mb = self._try("database_size", lambda: _pair(self.database_size(conn)),
                                        failed=(None, None))
        return HealthReading(
            process=self.process,
            cpu_pct=self._try("cpu_pct", lambda: _percent(self.system.cpu_percent(interval=None))),
            memory_pct=self._try("memory_pct", lambda: _percent(self.system.virtual_memory().percent)),
            disk_pct=self._try("disk_pct", lambda: _percent(self.system.disk_usage(self.disk_path).percent)),
            api_calls=calls,
            rate_limit_remaining=min(remaining) if remaining else None,
            db_used_mb=used_mb,
            db_max_mb=max_mb,
        )

def start(process: str, disk_path: str = HEALTH_DISK_PATH, system=psutil, database_size=read_database_size,
          api_usage=read_api_usage) -> HealthReader:
    """Return a health reader for one process, with CPU primed; called once at startup, never on import

    psutil's first non-blocking CPU reading is always 0.0, so this makes that first call here.

    Parameters:
        process (str): One of PROCESSES ("bot", "fill_stream")
        disk_path (str): The disk to read, HEALTH_DISK_PATH by default
        system: psutil or a fake
        database_size: storage.health.database_size or a fake
        api_usage: alpaca_client.api_usage or a fake

    Returns:
        A HealthReader

    Raises:
        ValueError if process isn't one of PROCESSES
    """
    reader = HealthReader(process, disk_path, system, database_size, api_usage)
    reader._try("cpu_pct", lambda: system.cpu_percent(interval=None))
    return reader
