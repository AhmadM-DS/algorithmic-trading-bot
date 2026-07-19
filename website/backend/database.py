#Third party libraries
import pyodbc
import os

from dotenv import load_dotenv
load_dotenv()

def get_connection():
    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_NAME")
    username = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")

    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
    )
    return conn

def run_query(conn, sql):
    cursor = conn.cursor()
    cursor.execute(sql)
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    result = []
    for row in rows:
        result.append(dict(zip(columns, row)))
    return result

def run_query_params(conn, sql, params):
    cursor = conn.cursor()
    cursor.execute(sql, params)
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    result = []
    for row in rows:
        result.append(dict(zip(columns, row)))
    return result

def run_insert(conn, sql, params):
    """Runs a parameterized INSERT ... OUTPUT INSERTED.<col> statement and commits.
    Returns the value of the OUTPUT column (e.g. the new row's ID)."""
    cursor = conn.cursor()
    cursor.execute(sql, params)
    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else None

if __name__ == "__main__":
    with get_connection() as conn:
        result = run_query(conn, "SELECT TOP 5 * FROM Trades")
        print(result)