"""
test_monitoring_schema.py
Integration tests for migration 012: health_status's nullable readings and process column, health_status_hourly
and the database_write_failed skip code
"""

#Standard Library
from datetime import datetime

#Third Party Libraries
import pyodbc
import pytest

HOUR = datetime(2026, 11, 27, 15, 0)

def insert_beat(conn, process="bot", api_calls=0, errors=0):
    """Save one heartbeat row as the bot with every reading missing"""
    conn.execute("INSERT INTO health_status (process, api_calls, errors) VALUES (?, ?, ?)",
                 (process, api_calls, errors))

def insert_hour(conn, process="bot", hour_start=HOUR, beats=60):
    """Save one hourly rollup row as the bot"""
    conn.execute("INSERT INTO health_status_hourly (process, hour_start, beats, cycles, cpu_pct_min, cpu_pct_avg, "
                 "cpu_pct_max, api_calls_max, rate_limit_remaining_min, errors) "
                 "VALUES (?, ?, ?, 4, 1.5, 12.25, 80, 40, 150, 0)", (process, hour_start, beats))

def test_database_write_failed_skip_code_sits_after_kill_switch(bot_conn):
    """Seed database_write_failed between kill_switch (30) and audit_mismatch (40)"""

    row = bot_conn.execute("SELECT skip_reason_id, [description], [priority] FROM skip_reasons "
                           "WHERE code = 'database_write_failed'").fetchone()

    assert tuple(row) == (25, "A database save is failing", 35)

def test_heartbeat_with_every_reading_missing_is_saved(bot_conn):
    """Save a heartbeat whose readings all failed: only the process and the counts are required"""
    insert_beat(bot_conn, process="fill_stream")

    row = bot_conn.execute("SELECT process, cpu_pct, memory_pct, disk_pct, rate_limit_remaining, db_used_mb, "
                           "db_max_mb FROM health_status").fetchone()

    assert tuple(row) == ("fill_stream", None, None, None, None, None, None)

def test_heartbeat_without_process_is_refused(bot_conn):
    """Refuse a heartbeat that doesn't say which process wrote it"""
    with pytest.raises(pyodbc.IntegrityError, match="process"):
        bot_conn.execute("INSERT INTO health_status (api_calls, errors) VALUES (0, 0)")

def test_heartbeat_from_unknown_process_is_refused(bot_conn):
    """Refuse a process other than bot and fill_stream"""
    with pytest.raises(pyodbc.IntegrityError, match="ck_health_status_process"):
        insert_beat(bot_conn, process="screener")

@pytest.mark.parametrize("column", ["api_calls", "errors"])
def test_heartbeat_counts_stay_required(bot_conn, column):
    """Keep api_calls and errors required: they are 0 when idle, never missing"""
    with pytest.raises(pyodbc.IntegrityError, match=column):
        insert_beat(bot_conn, **{column: None})

def test_bot_can_delete_old_heartbeats(bot_conn):
    """Let the bot delete raw heartbeats once they're rolled up"""
    insert_beat(bot_conn)

    bot_conn.execute("DELETE FROM health_status WHERE process = 'bot'")

    assert bot_conn.execute("SELECT COUNT(health_status_id) FROM health_status").fetchone()[0] == 0

def test_hourly_rollup_is_saved(bot_conn):
    """Save one hour's rollup for a process"""
    insert_hour(bot_conn)

    row = bot_conn.execute("SELECT process, hour_start, beats, cpu_pct_avg FROM health_status_hourly").fetchone()

    assert (row.process, row.hour_start, row.beats, float(row.cpu_pct_avg)) == ("bot", HOUR, 60, 12.25)

def test_same_process_and_hour_is_saved_once(bot_conn):
    """Refuse a second rollup of the same process and hour, so a rerun can't double it"""
    insert_hour(bot_conn)

    with pytest.raises(pyodbc.IntegrityError, match="uq_health_status_hourly_process_hour"):
        insert_hour(bot_conn)

def test_each_process_gets_its_own_hour(bot_conn):
    """Save the bot's and the fill stream's rollups of the same hour side by side"""
    insert_hour(bot_conn, process="bot")

    insert_hour(bot_conn, process="fill_stream")

    assert bot_conn.execute("SELECT COUNT(health_status_hourly_id) FROM health_status_hourly").fetchone()[0] == 2

@pytest.mark.parametrize("hour_start", [datetime(2026, 11, 27, 15, 30), datetime(2026, 11, 27, 15, 0, 1)])
def test_hour_start_off_the_hour_is_refused(bot_conn, hour_start):
    """Refuse an hour_start that isn't on a whole UTC hour"""
    with pytest.raises(pyodbc.IntegrityError, match="ck_health_status_hourly_hour_start"):
        insert_hour(bot_conn, hour_start=hour_start)

def test_hour_without_beats_is_refused(bot_conn):
    """Refuse a rollup of zero heartbeats: an hour with none gets no row"""
    with pytest.raises(pyodbc.IntegrityError, match="ck_health_status_hourly_beats"):
        insert_hour(bot_conn, beats=0)

def test_hourly_from_unknown_process_is_refused(bot_conn):
    """Refuse a process other than bot and fill_stream"""
    with pytest.raises(pyodbc.IntegrityError, match="ck_health_status_hourly_process"):
        insert_hour(bot_conn, process="screener")

@pytest.mark.parametrize("statement", ["UPDATE health_status_hourly SET beats = 1 WHERE 1 = 0",
                                       "DELETE FROM health_status_hourly WHERE 1 = 0"])
def test_bot_cannot_change_hourly_rollups(bot_conn, statement):
    """Keep the hourly archive append-only"""
    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute(statement)
