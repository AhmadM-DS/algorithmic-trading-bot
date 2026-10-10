import pyodbc

from storage.connections import is_duplicate_error

def make_error(message):
    return pyodbc.IntegrityError("23000", f"[23000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]{message}")

def test_unique_constraint_is_duplicate():
    e = make_error("Violation of UNIQUE KEY constraint 'uq_tickers_ticker'. (2627) (SQLExecDirectW)")
    assert is_duplicate_error(e)

def test_unique_index_is_duplicate():
    e = make_error("Cannot insert duplicate key row in object 'dbo.x' with unique index 'ix_x'. (2601) (SQLExecDirectW)")
    assert is_duplicate_error(e)

def test_foreign_key_is_not_duplicate():
    e = make_error("The INSERT statement conflicted with the FOREIGN KEY constraint. (547) (SQLExecDirectW)")
    assert not is_duplicate_error(e)

def test_number_in_values_is_not_duplicate():
    e = make_error("Cannot insert the value NULL into column 'x', ticker_id 2627. (515) (SQLExecDirectW)")
    assert not is_duplicate_error(e)
