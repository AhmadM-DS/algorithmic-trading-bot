"""
test_claude_reader_permissions.py
Integration tests for migration 010: claude_reader_role reads only approved columns and changes nothing
"""

#Third Party Libraries
import pyodbc
import pytest

HIDDEN_COLUMNS = [("strategies", "budget"),
                  ("signals", "label_pnl"),
                  ("risk_decisions", "equity"),
                  ("risk_decisions", "buying_power"),
                  ("risk_decisions", "trading_budget"),
                  ("risk_decisions", "account_exposure"),
                  ("risk_decisions", "strategy_exposure"),
                  ("risk_decisions", "ticker_exposure"),
                  ("risk_decisions", "strategy_daily_pnl"),
                  ("risk_decisions", "strategy_drawdown"),
                  ("risk_decisions", "account_daily_change"),
                  ("risk_decisions", "start_equity"),
                  ("positions", "realized_pnl"),
                  ("positions", "max_gain"),
                  ("positions", "max_loss"),
                  ("bot_events", "details"),
                  ("account_activities", "quantity"),
                  ("account_activities", "price"),
                  ("account_activities", "net_amount"),
                  ("account_activities", "raw_json"),
                  ("audit_log", "alpaca_cash"),
                  ("audit_log", "expected_cash"),
                  ("audit_failures", "details"),
                  ("cash_adjustments", "amount")]

ALLOWED_COLUMNS = [("strategies", "strategy_id, strategy, time_frame, default_holding_type, updated_at, mode, "
                                  "budget_set_at"),
                   ("tickers", "ticker_id, ticker, first_seen, is_active, fill_override"),
                   ("skip_reasons", "skip_reason_id, code, [description], [priority]"),
                   ("signals", "signal_id, side, time_frame, holding_type, quantity, stop_price, target_price, "
                               "reason, generated_at, taken, [source], strategy_version, git_commit, "
                               "market_data_plan, data_feed, model_version, probability, label_source, "
                               "strategy_id, ticker_id, primary_skip_reason_id"),
                   ("signal_features", "feature_id, signal_id, [name], [value]"),
                   ("signal_skip_reasons", "signal_id, skip_reason_id"),
                   ("risk_decisions", "risk_decision_id, signal_id, sizer, sized_quantity, open_positions, "
                                      "shares_held, broker_shares"),
                   ("risk_decision_parameters", "risk_decision_parameter_id, risk_decision_id, [name], [provider], "
                                                "proposed, used, clamped, rate_limited, fell_back"),
                   ("order_reviews", "order_review_id, signal_id, signal_price, check_price, check_price_at, "
                                     "price_feed, price_move, max_price_move, reviewed_at"),
                   ("positions", "position_id, time_frame, holding_type, opened_at, closed_at, [status], "
                                 "entry_quantity, avg_entry_price, exit_reason, strategy_id, ticker_id, signal_id"),
                   ("orders", "order_id, client_order_id, alpaca_order_id, side, requested_quantity, filled_quantity, "
                              "order_type, time_in_force, submitted_at, [status], request_price, filled_price, "
                              "reject_reason, strategy_id, ticker_id, signal_id, position_id, parent_order_id, "
                              "exit_reason"),
                   ("trades", "trade_id, alpaca_fill_id, side, quantity, filled_at, fill_price, time_frame, "
                              "exit_reason, position_id, order_id, corrects_trade_id"),
                   ("watchlist_history", "watchlist_history_id, [date], [source], selected, ticker_id"),
                   ("data_health", "data_health_id, checked_at, time_frame, missing_candles, stale_last_timestamp, "
                                   "zero_volume, duplicates, empty_values, lag_seconds, market_data_plan, [status], "
                                   "ticker_id"),
                   ("bot_events", "bot_event_id, event_type, occurred_at, strategy_id"),
                   ("broker_events", "broker_event_id, alpaca_order_id, client_order_id, execution_id, event_type, "
                                     "ticker, event_at, received_at, raw_json"),
                   ("account_activities", "account_activity_id, alpaca_activity_id, alpaca_order_id, activity_type, "
                                          "activity_at, ticker, side, loaded_at"),
                   ("audit_log", "audit_id, audit_date, audit_type, run_at, fills_at_alpaca, fills_in_db, "
                                 "missing_in_db, missing_at_alpaca, [status], notes, resolved_at, not_run_reason, "
                                 "catch_up_fills, audit_fills, price_mismatches, quantity_mismatches, "
                                 "share_mismatches"),
                   ("audit_failures", "audit_failure_id, audit_id, kind, ticker, alpaca_fill_id"),
                   ("cash_adjustments", "cash_adjustment_id, effective_date, reason, note, created_at"),
                   ("health_status", "health_status_id, recorded_at, cpu_pct, memory_pct, disk_pct, cycle_seconds, "
                                     "tickers_checked, tickers_bad, api_calls, rate_limit_remaining, errors, "
                                     "db_used_mb, db_max_mb, process"),
                   ("health_status_hourly", "health_status_hourly_id, process, hour_start, beats, cycles, "
                                            "cpu_pct_min, cpu_pct_avg, cpu_pct_max, memory_pct_min, memory_pct_avg, "
                                            "memory_pct_max, disk_pct_min, disk_pct_avg, disk_pct_max, "
                                            "cycle_seconds_min, cycle_seconds_avg, cycle_seconds_max, api_calls_max, "
                                            "rate_limit_remaining_min, errors, db_used_mb_max, db_max_mb, "
                                            "rolled_up_at")]

BLOCKED_TABLES = ["payment_methods", "subscriptions", "expenses"]

READABLE_VIEWS = ["v_trades_current", "v_open_positions", "v_order_fill_mismatches", "v_open_audit_failures"]

BLOCKED_VIEWS = ["v_strategy_daily_pnl", "v_ticker_stats"]

WRITE_STATEMENTS = ["INSERT INTO tickers (ticker, first_seen) SELECT 'TEST', '2026-01-02' WHERE 1 = 0",
                    "UPDATE tickers SET is_active = 0 WHERE 1 = 0",
                    "DELETE FROM tickers WHERE 1 = 0"]

def test_reader_conn_runs_as_reader_user(reader_conn):
    """Run reader_conn as the test reader user"""
    assert reader_conn.execute("SELECT USER_NAME()").fetchone()[0] == "test_claude_reader"

@pytest.mark.parametrize("table, column", HIDDEN_COLUMNS)
def test_reader_cannot_read_hidden_column(reader_conn, table, column):
    """Refuse a money column, even in a table the reader can partly read"""
    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        reader_conn.execute(f"SELECT {column} FROM {table} WHERE 1 = 0")

@pytest.mark.parametrize("table, columns", ALLOWED_COLUMNS)
def test_reader_can_read_allowed_columns(reader_conn, table, columns):
    """Read every approved column of a readable table"""
    reader_conn.execute(f"SELECT {columns} FROM {table} WHERE 1 = 0")

@pytest.mark.parametrize("table", BLOCKED_TABLES)
def test_reader_cannot_read_blocked_table(reader_conn, table):
    """Refuse every column of a spending table"""
    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        reader_conn.execute(f"SELECT * FROM {table} WHERE 1 = 0")

@pytest.mark.parametrize("view", READABLE_VIEWS)
def test_reader_can_read_view(reader_conn, view):
    """Read a view that shows only approved columns"""
    reader_conn.execute(f"SELECT * FROM {view} WHERE 1 = 0")

@pytest.mark.parametrize("view", BLOCKED_VIEWS)
def test_reader_cannot_read_profit_view(reader_conn, view):
    """Refuse a view that shows realized profit, since a view grant would skip the column checks"""
    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        reader_conn.execute(f"SELECT * FROM {view} WHERE 1 = 0")

@pytest.mark.parametrize("statement", WRITE_STATEMENTS)
def test_reader_cannot_write(reader_conn, statement):
    """Refuse an insert, update or delete on a table the reader can read"""
    with pytest.raises(pyodbc.ProgrammingError, match="permission"):
        reader_conn.execute(statement)

def test_reader_is_only_in_its_own_role(admin_conn):
    """Keep the reader out of bot_role and report_role"""
    roles = admin_conn.execute("SELECT r.name FROM sys.database_role_members m "
                               "JOIN sys.database_principals r ON r.principal_id = m.role_principal_id "
                               "JOIN sys.database_principals u ON u.principal_id = m.member_principal_id "
                               "WHERE u.name = 'test_claude_reader'").fetchall()
    assert [row[0] for row in roles] == ["claude_reader_role"]

def test_public_has_no_table_grants(admin_conn):
    """Give public no rights on any dbo table or view, so nothing reaches the reader through it"""
    grants = admin_conn.execute("SELECT COUNT(*) FROM sys.database_permissions p "
                                "JOIN sys.database_principals g ON g.principal_id = p.grantee_principal_id "
                                "WHERE g.name = 'public' AND p.class = 1 "
                                "AND OBJECT_SCHEMA_NAME(p.major_id) = 'dbo'").fetchone()[0]
    assert grants == 0

def _classified_columns() -> set:
    """Return every (table, column) pair the lists above put on the allowed or hidden side"""
    allowed = {(table, column.strip().strip("[]")) for table, columns in ALLOWED_COLUMNS
               for column in columns.split(",")}
    return allowed | set(HIDDEN_COLUMNS)

def _table_columns_read_by(conn, view: str) -> set:
    """Return every (table, column) pair a view reads, following views it reads in turn"""
    rows = conn.execute("SELECT r.referenced_entity_name, r.referenced_minor_name, o.type "
                        "FROM sys.dm_sql_referenced_entities(?, 'OBJECT') r "
                        "JOIN sys.objects o ON o.object_id = r.referenced_id", f"dbo.{view}").fetchall()
    columns = set()
    for name, column, object_type in rows:
        if object_type.strip() == "V" and column is None:
            columns |= _table_columns_read_by(conn, name)
        elif object_type.strip() == "U":
            columns.add((name, column))
    return columns

def test_every_table_column_is_classified(admin_conn):
    """Fail on any new table or column until it is listed as allowed, hidden or in a blocked table"""
    rows = admin_conn.execute("SELECT c.TABLE_NAME, c.COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS c "
                              "JOIN INFORMATION_SCHEMA.TABLES t ON t.TABLE_SCHEMA = c.TABLE_SCHEMA "
                              "AND t.TABLE_NAME = c.TABLE_NAME "
                              "WHERE c.TABLE_SCHEMA = 'dbo' AND t.TABLE_TYPE = 'BASE TABLE'").fetchall()
    unclassified = {(table, column) for table, column in rows
                    if table not in BLOCKED_TABLES and (table, column) not in _classified_columns()}
    assert unclassified == set()

def test_granted_views_read_no_hidden_data(admin_conn):
    """Fail if a view granted to the reader reads a hidden column or a blocked table beneath it"""
    views = admin_conn.execute("SELECT o.name FROM sys.database_permissions p "
                               "JOIN sys.database_principals g ON g.principal_id = p.grantee_principal_id "
                               "JOIN sys.objects o ON o.object_id = p.major_id "
                               "WHERE g.name = 'claude_reader_role' AND o.type = 'V' "
                               "AND p.permission_name = 'SELECT'").fetchall()
    leaks = {(view, table, column) for (view,) in views for table, column in _table_columns_read_by(admin_conn, view)
             if table in BLOCKED_TABLES or (table, column) in HIDDEN_COLUMNS}
    assert leaks == set()
