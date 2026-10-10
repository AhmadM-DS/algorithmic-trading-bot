"""
conftest.py
Integration test setup: rebuilds noctis_test from the migrations before the tests run.
"""

#Standard Library
import os
from pathlib import Path

#Third Party Libraries
import pyodbc
import pytest

SQL_DIR = Path(__file__).parent.parent.parent / "sql"
# views.sql creates the report schema that 002 grants on, so it runs before 002.
BUILD_FILES = [SQL_DIR / "migrations" / "001_initial_schema.sql",
               SQL_DIR / "views.sql",
               SQL_DIR / "migrations" / "002_roles.sql"]

# Never read from .env: this database gets dropped on every run.
TEST_DB = "noctis_test"
TEST_SERVER = os.environ.get("TEST_DB_SERVER", r"localhost\SQLEXPRESS")
TEST_BOT_USER = "test_bot"

def split_batches(sql_text):
    """Read a sql file and split where 'GO' is found to avoid conflictions"""
    batches = []
    current = []
    for line in sql_text.splitlines():
        if line.strip().upper() == "GO":
            batch = "\n".join(current)
            if batch.strip():
                batches.append(batch)
            current = []
        else:
            current.append(line)
    batch = "\n".join(current)
    if batch.strip():
        batches.append(batch)
    return batches

def admin_connect(database, autocommit):
    """Connect as the Windows user (admin on the local server)"""
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={TEST_SERVER};"
        f"DATABASE={database};"
        "Trusted_Connection=yes;"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;",
        autocommit=autocommit,
    )

def run_batch(cursor, batch):
    cursor.execute(batch)
    # pyodbc only raises an error from a later statement in the batch once its result is read
    while cursor.nextset():
        pass

@pytest.fixture(scope="session")
def test_db():
    """Drop and rebuild noctis_test once per pytest run"""
    master = admin_connect("master", autocommit=True)
    cursor = master.cursor()
    run_batch(cursor, f"""
        IF DB_ID('{TEST_DB}') IS NOT NULL
        BEGIN
            ALTER DATABASE {TEST_DB} SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
            DROP DATABASE {TEST_DB};
        END""")
    run_batch(cursor, f"CREATE DATABASE {TEST_DB};")
    master.close()

    conn = admin_connect(TEST_DB, autocommit=True)
    cursor = conn.cursor()
    for path in BUILD_FILES:
        for batch in split_batches(path.read_text()):
            run_batch(cursor, batch)
    run_batch(cursor, f"CREATE USER {TEST_BOT_USER} WITHOUT LOGIN;")
    run_batch(cursor, f"ALTER ROLE bot_role ADD MEMBER {TEST_BOT_USER};")
    conn.close()
    yield TEST_DB

@pytest.fixture
def bot_conn(test_db):
    """A connection that runs as a bot_role member; every change is rolled back after the test"""
    conn = admin_connect(test_db, autocommit=False)
    conn.execute(f"EXECUTE AS USER = '{TEST_BOT_USER}';")
    yield conn
    conn.rollback()
    conn.execute("REVERT;")
    conn.close()
