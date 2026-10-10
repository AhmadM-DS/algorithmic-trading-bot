"""
connections.py
Connect to the database and shared helpers for every storage file
"""

#Standard Library
import os

#Third Party Libraries
import pandas as pd
import pyodbc

#Local Imports
from logger import db_log

def is_duplicate_error(e):
    """Check whether a database error is a UNIQUE violation

    Matches SQL Server errors 2627 (UNIQUE constraint) and 2601 (unique index) only,
    so foreign key, CHECK and NULL errors aren't mistaken for duplicates.

    Parameters:
        e (pyodbc.Error): The caught database error

    Returns:
        True if the error is a duplicate
    """
    error_message = str(e)
    ssms_error_numbers = ["(2627)", "(2601)"]
    if any(number in error_message for number in ssms_error_numbers):
        return True
    return False

def to_db_time(value):
    """Return a timestamp as naive UTC for a DATETIME2 column

    pyodbc drops the timezone and stores the clock reading as-is, so a New York time
    would be saved as if it were UTC. Converting first prevents that.

    Parameters:
        value (datetime | Timestamp | None): A timezone-aware time

    Returns:
        A naive UTC datetime, or None if value is None

    Raises:
        TypeError if value has no timezone (it can't be converted safely)
    """
    if value is None:
        return None
    return pd.Timestamp(value).tz_convert("UTC").tz_localize(None).to_pydatetime()

def get_connection():
    """Open a database connection from the DB_* settings in .env

    DB_TRUST_SERVER_CERT is yes locally and no on Azure. The caller closes the
    connection at the end of the cycle.

    Returns:
        An open pyodbc connection (autocommit off)

    Raises:
        pyodbc.Error if the connection fails (logged first)
    """
    server = os.environ["DB_SERVER"]
    database = os.environ["DB_NAME"]
    username = os.environ["DB_USER"]
    password = os.environ["DB_PASSWORD"]
    trust_server_cert = os.environ["DB_TRUST_SERVER_CERT"]

    try:
        conn = pyodbc.connect(
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
            "Encrypt=yes;"
            f"TrustServerCertificate={trust_server_cert};"
        )
        db_log.debug(f"Connected to {database} on {server}")
    except pyodbc.Error as e:
        db_log.error(f"Failure to connect {database} on {server}. Message: {e}")
        raise
    return conn
