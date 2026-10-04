SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF SCHEMA_ID('report') IS NULL
    EXEC('CREATE SCHEMA report');
GO

-- Walks each correction chain back to the original fill, so every current
-- row keeps the Alpaca fill ID the audit matches on.
CREATE OR ALTER VIEW dbo.v_trades_current
AS
WITH chain AS
(
    SELECT trade_id, trade_id AS root_trade_id, alpaca_fill_id AS root_alpaca_fill_id
    FROM dbo.trades
    WHERE corrects_trade_id IS NULL

    UNION ALL

    SELECT c.trade_id, chain.root_trade_id, chain.root_alpaca_fill_id
    FROM dbo.trades c
    JOIN chain ON c.corrects_trade_id = chain.trade_id
)
SELECT
    t.trade_id,
    chain.root_trade_id,
    chain.root_alpaca_fill_id AS alpaca_fill_id,
    t.side,
    t.quantity,
    t.filled_at,
    t.fill_price,
    t.time_frame,
    t.exit_reason,
    t.position_id,
    t.order_id,
    CAST(CASE WHEN t.corrects_trade_id IS NULL THEN 0 ELSE 1 END AS BIT) AS is_correction
FROM dbo.trades t
JOIN chain ON chain.trade_id = t.trade_id
WHERE NOT EXISTS (SELECT 1 FROM dbo.trades newer WHERE newer.corrects_trade_id = t.trade_id);
GO

CREATE OR ALTER VIEW dbo.v_open_positions
AS
SELECT
    p.position_id,
    p.strategy_id,
    s.strategy,
    p.ticker_id,
    tk.ticker,
    p.time_frame,
    p.holding_type,
    p.opened_at,
    p.entry_quantity,
    p.avg_entry_price,
    ISNULL(f.shares_bought, 0) AS shares_bought,
    ISNULL(f.shares_sold, 0) AS shares_sold,
    ISNULL(f.shares_bought, 0) - ISNULL(f.shares_sold, 0) AS shares_held
FROM dbo.positions p
JOIN dbo.strategies s ON s.strategy_id = p.strategy_id
JOIN dbo.tickers tk ON tk.ticker_id = p.ticker_id
LEFT JOIN
(
    SELECT
        position_id,
        SUM(CASE WHEN side = 'buy'  THEN quantity ELSE 0 END) AS shares_bought,
        SUM(CASE WHEN side = 'sell' THEN quantity ELSE 0 END) AS shares_sold
    FROM dbo.v_trades_current
    GROUP BY position_id
) f ON f.position_id = p.position_id
WHERE p.[status] = 'open';
GO

-- The trading day is an Eastern-time date, so this is the one bot view that
-- converts from UTC.
CREATE OR ALTER VIEW dbo.v_strategy_daily_pnl
AS
SELECT
    p.strategy_id,
    s.strategy,
    p.holding_type,
    CAST(p.closed_at AT TIME ZONE 'UTC' AT TIME ZONE 'Eastern Standard Time' AS DATE) AS trade_date_et,
    COUNT(*) AS positions_closed,
    SUM(CASE WHEN p.realized_pnl > 0 THEN 1 ELSE 0 END) AS winning_positions,
    SUM(p.realized_pnl) AS realized_pnl
FROM dbo.positions p
JOIN dbo.strategies s ON s.strategy_id = p.strategy_id
WHERE p.[status] = 'closed'
GROUP BY
    p.strategy_id,
    s.strategy,
    p.holding_type,
    CAST(p.closed_at AT TIME ZONE 'UTC' AT TIME ZONE 'Eastern Standard Time' AS DATE);
GO

CREATE OR ALTER VIEW dbo.v_order_fill_mismatches
AS
SELECT
    o.order_id,
    o.alpaca_order_id,
    o.client_order_id,
    o.[status],
    o.filled_quantity,
    ISNULL(f.quantity_in_trades, 0) AS quantity_in_trades,
    o.filled_quantity - ISNULL(f.quantity_in_trades, 0) AS difference
FROM dbo.orders o
LEFT JOIN
(
    SELECT order_id, SUM(quantity) AS quantity_in_trades
    FROM dbo.v_trades_current
    GROUP BY order_id
) f ON f.order_id = o.order_id
WHERE o.filled_quantity <> ISNULL(f.quantity_in_trades, 0);
GO

CREATE OR ALTER VIEW dbo.v_open_audit_failures
AS
SELECT
    audit_id,
    audit_date,
    audit_type,
    run_at,
    fills_at_alpaca,
    fills_in_db,
    missing_in_db,
    missing_at_alpaca,
    notes
FROM dbo.audit_log
WHERE [status] = 'fail'
  AND resolved_at IS NULL;
GO

CREATE OR ALTER VIEW dbo.v_ticker_stats
AS
SELECT
    tk.ticker_id,
    tk.ticker,
    tk.first_seen,
    tk.is_active,
    ISNULL(w.days_appeared, 0) AS days_appeared,
    ISNULL(w.days_selected, 0) AS days_selected,
    w.last_appeared,
    ISNULL(p.closed_positions, 0) AS closed_positions,
    ISNULL(p.profitable_trades, 0) AS profitable_trades,
    ROW_NUMBER() OVER (
        ORDER BY ISNULL(w.days_appeared, 0) DESC, ISNULL(p.profitable_trades, 0) DESC, tk.ticker
    ) AS popularity_rank
FROM dbo.tickers tk
LEFT JOIN
(
    SELECT
        ticker_id,
        COUNT(DISTINCT [date]) AS days_appeared,
        COUNT(DISTINCT CASE WHEN selected = 1 THEN [date] END) AS days_selected,
        MAX([date]) AS last_appeared
    FROM dbo.watchlist_history
    GROUP BY ticker_id
) w ON w.ticker_id = tk.ticker_id
LEFT JOIN
(
    SELECT
        ticker_id,
        COUNT(*) AS closed_positions,
        SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS profitable_trades
    FROM dbo.positions
    WHERE [status] = 'closed'
    GROUP BY ticker_id
) p ON p.ticker_id = tk.ticker_id;
GO
