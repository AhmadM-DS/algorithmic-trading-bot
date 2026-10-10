import pyodbc
import pytest

def test_bot_conn_runs_as_bot_role(bot_conn):
    assert bot_conn.execute("SELECT USER_NAME()").fetchone()[0] == "test_bot"

def test_bot_conn_cannot_update_strategies(bot_conn):
    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        bot_conn.execute("UPDATE strategies SET is_active = 0 WHERE 1 = 0")
