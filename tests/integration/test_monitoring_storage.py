"""
test_monitoring_storage.py
Integration tests for storage/health.py's database_size, run as the bot's role
"""

#Local Imports
from storage.health import database_size

def test_bot_can_read_the_database_size(bot_conn):
    """Read the used size as bot_role, so the heartbeat works in prod without extra grants"""

    used_mb, max_mb = database_size(bot_conn)

    assert isinstance(used_mb, int) and used_mb > 0
    assert max_mb is None or max_mb > 0
