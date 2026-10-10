"""
connections.py
Connect to the database
"""

#Standard Library
import os

#Third Party Libraries
import pyodbc
from logger import db_log

def is_duplicate_error(e):
    error_message = str(e)
    ssms_error_numbers = ["(2627)", "(2601)"]
    if any(number in error_message for number in ssms_error_numbers):
        return True
    return False

def get_connection():
    """Connect to the database depending on TrustServerCertificate"""
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