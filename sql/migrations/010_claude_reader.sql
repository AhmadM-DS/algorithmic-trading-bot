CREATE ROLE claude_reader_role;
GO

GRANT SELECT ON dbo.strategies (strategy_id, strategy, time_frame, default_holding_type, updated_at, mode,
    budget_set_at) TO claude_reader_role;
GRANT SELECT ON dbo.tickers (ticker_id, ticker, first_seen, is_active, fill_override) TO claude_reader_role;
GRANT SELECT ON dbo.skip_reasons (skip_reason_id, code, [description], [priority]) TO claude_reader_role;
GRANT SELECT ON dbo.signals (signal_id, side, time_frame, holding_type, quantity, stop_price, target_price,
    reason, generated_at, taken, [source], strategy_version, git_commit, market_data_plan, data_feed,
    model_version, probability, label_source, strategy_id, ticker_id, primary_skip_reason_id) TO claude_reader_role;
GRANT SELECT ON dbo.signal_features (feature_id, signal_id, [name], [value]) TO claude_reader_role;
GRANT SELECT ON dbo.signal_skip_reasons (signal_id, skip_reason_id) TO claude_reader_role;
GRANT SELECT ON dbo.risk_decisions (risk_decision_id, signal_id, sizer, sized_quantity, open_positions,
    shares_held, broker_shares) TO claude_reader_role;
GRANT SELECT ON dbo.risk_decision_parameters (risk_decision_parameter_id, risk_decision_id, [name], [provider],
    proposed, used, clamped, rate_limited, fell_back) TO claude_reader_role;
GRANT SELECT ON dbo.order_reviews (order_review_id, signal_id, signal_price, check_price, check_price_at,
    price_feed, price_move, max_price_move, reviewed_at) TO claude_reader_role;
GRANT SELECT ON dbo.positions (position_id, time_frame, holding_type, opened_at, closed_at, [status],
    entry_quantity, avg_entry_price, exit_reason, strategy_id, ticker_id, signal_id) TO claude_reader_role;
GRANT SELECT ON dbo.orders (order_id, client_order_id, alpaca_order_id, side, requested_quantity, filled_quantity,
    order_type, time_in_force, submitted_at, [status], request_price, filled_price, reject_reason, strategy_id,
    ticker_id, signal_id, position_id, parent_order_id, exit_reason) TO claude_reader_role;
GRANT SELECT ON dbo.trades (trade_id, alpaca_fill_id, side, quantity, filled_at, fill_price, time_frame,
    exit_reason, position_id, order_id, corrects_trade_id) TO claude_reader_role;
GRANT SELECT ON dbo.watchlist_history (watchlist_history_id, [date], [source], selected, ticker_id)
    TO claude_reader_role;
GRANT SELECT ON dbo.data_health (data_health_id, checked_at, time_frame, missing_candles, stale_last_timestamp,
    zero_volume, duplicates, empty_values, lag_seconds, market_data_plan, [status], ticker_id) TO claude_reader_role;
GRANT SELECT ON dbo.bot_events (bot_event_id, event_type, occurred_at, strategy_id) TO claude_reader_role;
GRANT SELECT ON dbo.broker_events (broker_event_id, alpaca_order_id, client_order_id, execution_id, event_type,
    ticker, event_at, received_at, raw_json) TO claude_reader_role;
GRANT SELECT ON dbo.account_activities (account_activity_id, alpaca_activity_id, alpaca_order_id, activity_type,
    activity_at, ticker, side, loaded_at) TO claude_reader_role;
GRANT SELECT ON dbo.audit_log (audit_id, audit_date, audit_type, run_at, fills_at_alpaca, fills_in_db,
    missing_in_db, missing_at_alpaca, [status], notes, resolved_at) TO claude_reader_role;
GRANT SELECT ON dbo.health_status (health_status_id, recorded_at, cpu_pct, memory_pct, disk_pct, cycle_seconds,
    tickers_checked, tickers_bad, api_calls, rate_limit_remaining, errors, db_used_mb, db_max_mb)
    TO claude_reader_role;
GO
