-- Required for the filtered (WHERE) indexes; sqlcmd turns QUOTED_IDENTIFIER off by default.
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

CREATE TABLE strategies
(
    strategy_id          INT IDENTITY(1,1) NOT NULL,
    strategy             NVARCHAR(50)  NOT NULL,
    time_frame           NVARCHAR(10)  NOT NULL,
    default_holding_type NVARCHAR(10)  NOT NULL,
    budget               DECIMAL(19,4) NOT NULL,
    updated_at           DATETIME2     NOT NULL CONSTRAINT df_strategies_updated_at DEFAULT SYSUTCDATETIME(),
    is_active            BIT           NOT NULL CONSTRAINT df_strategies_is_active DEFAULT 1,
    CONSTRAINT pk_strategies PRIMARY KEY (strategy_id),
    CONSTRAINT uq_strategies_strategy UNIQUE (strategy),
    CONSTRAINT ck_strategies_default_holding_type CHECK (default_holding_type IN ('day', 'swing')),
    CONSTRAINT ck_strategies_budget CHECK (budget >= 0)
);
GO

CREATE TABLE tickers
(
    ticker_id  INT IDENTITY(1,1) NOT NULL,
    ticker     NVARCHAR(10) NOT NULL,
    first_seen DATE         NOT NULL,
    is_active  BIT          NOT NULL CONSTRAINT df_tickers_is_active DEFAULT 1,
    CONSTRAINT pk_tickers PRIMARY KEY (ticker_id),
    CONSTRAINT uq_tickers_ticker UNIQUE (ticker)
);
GO

CREATE TABLE payment_methods
(
    payment_method_id INT IDENTITY(1,1) NOT NULL,
    payment_used      NVARCHAR(50) NOT NULL,
    CONSTRAINT pk_payment_methods PRIMARY KEY (payment_method_id),
    CONSTRAINT uq_payment_methods_payment_used UNIQUE (payment_used)
);
GO

CREATE TABLE signals
(
    signal_id        INT IDENTITY(1,1) NOT NULL,
    side             NVARCHAR(5)   NOT NULL,
    time_frame       NVARCHAR(10)  NOT NULL,
    holding_type     NVARCHAR(10)  NOT NULL,
    quantity         INT           NOT NULL,
    stop_price       DECIMAL(19,4) NULL,
    target_price     DECIMAL(19,4) NULL,
    reason           NVARCHAR(256) NOT NULL,
    generated_at     DATETIME2     NOT NULL,
    taken            BIT           NOT NULL,
    skip_reason      NVARCHAR(256) NULL,
    [source]         NVARCHAR(10)  NOT NULL,
    strategy_version NVARCHAR(20)  NOT NULL,
    git_commit       NVARCHAR(40)  NOT NULL,
    market_data_plan NVARCHAR(20)  NOT NULL,
    data_feed        NVARCHAR(20)  NOT NULL,
    model_version    NVARCHAR(20)  NULL,
    probability      DECIMAL(5,4)  NULL,
    label_pnl        DECIMAL(19,4) NULL,
    label_source     NVARCHAR(10)  NULL,
    strategy_id      INT           NOT NULL,
    ticker_id        INT           NOT NULL,
    CONSTRAINT pk_signals PRIMARY KEY (signal_id),
    CONSTRAINT fk_signals_strategy_id FOREIGN KEY (strategy_id) REFERENCES strategies (strategy_id),
    CONSTRAINT fk_signals_ticker_id   FOREIGN KEY (ticker_id)   REFERENCES tickers (ticker_id),
    CONSTRAINT ck_signals_side         CHECK (side IN ('buy', 'sell')),
    CONSTRAINT ck_signals_holding_type CHECK (holding_type IN ('day', 'swing')),
    CONSTRAINT ck_signals_quantity     CHECK (quantity >= 0),
    CONSTRAINT ck_signals_source       CHECK ([source] IN ('live', 'backtest')),
    CONSTRAINT ck_signals_probability  CHECK (probability BETWEEN 0 AND 1),
    CONSTRAINT ck_signals_label_source CHECK (label_source IN ('actual', 'simulated')),

    CONSTRAINT ck_signals_taken_skip_reason CHECK (
        (taken = 1 AND skip_reason IS NULL) OR (taken = 0 AND skip_reason IS NOT NULL)
    )
);
GO

CREATE INDEX ix_signals_strategy_id_generated_at ON signals (strategy_id, generated_at);
CREATE INDEX ix_signals_ticker_id ON signals (ticker_id);
CREATE INDEX ix_signals_generated_at ON signals (generated_at);
GO

CREATE TABLE signal_features
(
    feature_id BIGINT IDENTITY(1,1) NOT NULL,
    signal_id  INT          NOT NULL,
    [name]     NVARCHAR(50) NOT NULL,
    [value]    FLOAT        NOT NULL,
    CONSTRAINT pk_signal_features PRIMARY KEY (feature_id),
    CONSTRAINT fk_signal_features_signal_id FOREIGN KEY (signal_id) REFERENCES signals (signal_id),
    CONSTRAINT uq_signal_features_signal_id_name UNIQUE (signal_id, [name])
);
GO

CREATE TABLE positions
(
    position_id     INT IDENTITY(1,1) NOT NULL,
    time_frame      NVARCHAR(10)  NOT NULL,
    holding_type    NVARCHAR(10)  NOT NULL,
    opened_at       DATETIME2     NOT NULL,
    closed_at       DATETIME2     NULL,
    [status]        NVARCHAR(25)  NOT NULL,
    entry_quantity  INT           NOT NULL,
    avg_entry_price DECIMAL(19,4) NOT NULL,
    realized_pnl    DECIMAL(19,4) NULL,
    max_gain        DECIMAL(19,4) NULL,
    max_loss        DECIMAL(19,4) NULL,
    exit_reason     NVARCHAR(50)  NULL,
    strategy_id     INT           NOT NULL,
    ticker_id       INT           NOT NULL,
    signal_id       INT           NULL,
    CONSTRAINT pk_positions PRIMARY KEY (position_id),
    CONSTRAINT fk_positions_strategy_id FOREIGN KEY (strategy_id) REFERENCES strategies (strategy_id),
    CONSTRAINT fk_positions_ticker_id   FOREIGN KEY (ticker_id)   REFERENCES tickers (ticker_id),
    CONSTRAINT fk_positions_signal_id   FOREIGN KEY (signal_id)   REFERENCES signals (signal_id),
    CONSTRAINT ck_positions_holding_type   CHECK (holding_type IN ('day', 'swing')),
    CONSTRAINT ck_positions_status         CHECK ([status] IN ('open', 'closed')),
    CONSTRAINT ck_positions_entry_quantity CHECK (entry_quantity > 0),
    CONSTRAINT ck_positions_exit_reason    CHECK (exit_reason IN
        ('signal', 'take_profit', 'stop_loss', 'end_of_day', 'kill_switch', 'manual', 'liquidation')),

    CONSTRAINT ck_positions_closed CHECK (
        ([status] = 'open'   AND closed_at IS NULL     AND exit_reason IS NULL) OR
        ([status] = 'closed' AND closed_at IS NOT NULL AND exit_reason IS NOT NULL)
    )
);
GO

CREATE UNIQUE INDEX uq_positions_signal_id ON positions (signal_id) WHERE signal_id IS NOT NULL;
CREATE INDEX ix_positions_strategy_id ON positions (strategy_id);
CREATE INDEX ix_positions_ticker_id ON positions (ticker_id);
CREATE INDEX ix_positions_opened_at ON positions (opened_at);
CREATE INDEX ix_positions_open ON positions (strategy_id, ticker_id) WHERE [status] = 'open';
GO

CREATE TABLE orders
(
    order_id           INT IDENTITY(1,1) NOT NULL,
    client_order_id    NVARCHAR(128) NOT NULL,
    alpaca_order_id    NVARCHAR(128) NULL,
    side               NVARCHAR(5)   NOT NULL,
    requested_quantity INT           NOT NULL,
    filled_quantity    INT           NOT NULL CONSTRAINT df_orders_filled_quantity DEFAULT 0,
    order_type         NVARCHAR(25)  NOT NULL,
    time_in_force      NVARCHAR(25)  NOT NULL,
    submitted_at       DATETIME2     NOT NULL,
    [status]           NVARCHAR(25)  NOT NULL,
    request_price      DECIMAL(19,4) NULL,
    filled_price       DECIMAL(19,4) NULL,
    reject_reason      NVARCHAR(256) NULL,
    strategy_id        INT           NOT NULL,
    ticker_id          INT           NOT NULL,
    signal_id          INT           NULL,
    position_id        INT           NULL,
    CONSTRAINT pk_orders PRIMARY KEY (order_id),
    CONSTRAINT fk_orders_strategy_id FOREIGN KEY (strategy_id) REFERENCES strategies (strategy_id),
    CONSTRAINT fk_orders_ticker_id   FOREIGN KEY (ticker_id)   REFERENCES tickers (ticker_id),
    CONSTRAINT fk_orders_signal_id   FOREIGN KEY (signal_id)   REFERENCES signals (signal_id),
    CONSTRAINT fk_orders_position_id FOREIGN KEY (position_id) REFERENCES positions (position_id),
    CONSTRAINT uq_orders_client_order_id UNIQUE (client_order_id),
    CONSTRAINT ck_orders_side CHECK (side IN ('buy', 'sell')),
    CONSTRAINT ck_orders_requested_quantity CHECK (requested_quantity > 0),
    CONSTRAINT ck_orders_filled_quantity CHECK (filled_quantity >= 0 AND filled_quantity <= requested_quantity)
);
GO

CREATE UNIQUE INDEX uq_orders_alpaca_order_id ON orders (alpaca_order_id) WHERE alpaca_order_id IS NOT NULL;
CREATE INDEX ix_orders_strategy_id ON orders (strategy_id);
CREATE INDEX ix_orders_ticker_id ON orders (ticker_id);
CREATE INDEX ix_orders_signal_id ON orders (signal_id);
CREATE INDEX ix_orders_position_id ON orders (position_id);
CREATE INDEX ix_orders_submitted_at ON orders (submitted_at);
GO

CREATE TABLE trades
(
    trade_id          INT IDENTITY(1,1) NOT NULL,
    alpaca_fill_id    NVARCHAR(128) NULL,
    side              NVARCHAR(5)   NOT NULL,
    quantity          INT           NOT NULL,
    filled_at         DATETIME2     NOT NULL,
    fill_price        DECIMAL(19,4) NOT NULL,
    time_frame        NVARCHAR(10)  NOT NULL,
    exit_reason       NVARCHAR(50)  NULL,
    position_id       INT           NOT NULL,
    order_id          INT           NOT NULL,
    corrects_trade_id INT           NULL,
    CONSTRAINT pk_trades PRIMARY KEY (trade_id),
    CONSTRAINT fk_trades_position_id       FOREIGN KEY (position_id)       REFERENCES positions (position_id),
    CONSTRAINT fk_trades_order_id          FOREIGN KEY (order_id)          REFERENCES orders (order_id),
    CONSTRAINT fk_trades_corrects_trade_id FOREIGN KEY (corrects_trade_id) REFERENCES trades (trade_id),
    CONSTRAINT ck_trades_side     CHECK (side IN ('buy', 'sell')),
    CONSTRAINT ck_trades_quantity CHECK (quantity > 0),
    CONSTRAINT ck_trades_exit_reason CHECK (exit_reason IN
        ('signal', 'take_profit', 'stop_loss', 'end_of_day', 'kill_switch', 'manual', 'liquidation')),
    CONSTRAINT ck_trades_exit_reason_sells_only CHECK (side = 'sell' OR exit_reason IS NULL),

    CONSTRAINT ck_trades_fill_or_correction CHECK (alpaca_fill_id IS NOT NULL OR corrects_trade_id IS NOT NULL)
);
GO

CREATE UNIQUE INDEX uq_trades_alpaca_fill_id ON trades (alpaca_fill_id) WHERE alpaca_fill_id IS NOT NULL;
CREATE INDEX ix_trades_position_id ON trades (position_id);
CREATE INDEX ix_trades_order_id ON trades (order_id);
CREATE INDEX ix_trades_filled_at ON trades (filled_at);
GO

CREATE TABLE watchlist_history
(
    watchlist_history_id INT IDENTITY(1,1) NOT NULL,
    [date]               DATE         NOT NULL,
    [source]             NVARCHAR(50) NOT NULL,
    selected             BIT          NOT NULL,
    ticker_id            INT          NOT NULL,
    CONSTRAINT pk_watchlist_history PRIMARY KEY (watchlist_history_id),
    CONSTRAINT fk_watchlist_history_ticker_id FOREIGN KEY (ticker_id) REFERENCES tickers (ticker_id),
    CONSTRAINT uq_watchlist_history_date_ticker_source UNIQUE ([date], ticker_id, [source])
);
GO

CREATE INDEX ix_watchlist_history_ticker_id ON watchlist_history (ticker_id);
GO

CREATE TABLE data_health
(
    data_health_id       INT IDENTITY(1,1) NOT NULL,
    checked_at           DATETIME2    NOT NULL,
    time_frame           NVARCHAR(10) NOT NULL,
    missing_candles      INT          NOT NULL,
    stale_last_timestamp DATETIME2    NULL,
    zero_volume          INT          NOT NULL,
    duplicates           INT          NOT NULL,
    empty_values         INT          NOT NULL,
    lag_seconds          INT          NULL,
    market_data_plan     NVARCHAR(10) NOT NULL,
    [status]             NVARCHAR(25) NOT NULL,
    ticker_id            INT          NOT NULL,
    CONSTRAINT pk_data_health PRIMARY KEY (data_health_id),
    CONSTRAINT fk_data_health_ticker_id FOREIGN KEY (ticker_id) REFERENCES tickers (ticker_id),
    CONSTRAINT ck_data_health_status CHECK ([status] IN ('ok', 'warn', 'bad'))
);
GO

CREATE INDEX ix_data_health_ticker_id ON data_health (ticker_id);
CREATE INDEX ix_data_health_checked_at ON data_health (checked_at);
GO

CREATE TABLE bot_events
(
    bot_event_id INT IDENTITY(1,1) NOT NULL,
    event_type   NVARCHAR(50)  NOT NULL,
    occurred_at  DATETIME2     NOT NULL CONSTRAINT df_bot_events_occurred_at DEFAULT SYSUTCDATETIME(),
    details      NVARCHAR(MAX) NULL,
    strategy_id  INT           NULL,
    CONSTRAINT pk_bot_events PRIMARY KEY (bot_event_id),
    CONSTRAINT fk_bot_events_strategy_id FOREIGN KEY (strategy_id) REFERENCES strategies (strategy_id)
);
GO

CREATE INDEX ix_bot_events_occurred_at ON bot_events (occurred_at);
CREATE INDEX ix_bot_events_strategy_id ON bot_events (strategy_id);
GO

CREATE TABLE subscriptions
(
    subscription_id   INT IDENTITY(1,1) NOT NULL,
    service_name      NVARCHAR(50)  NOT NULL,
    [provider]        NVARCHAR(50)  NOT NULL,
    purpose           NVARCHAR(250) NULL,
    cost              DECIMAL(19,4) NOT NULL,
    billing_cycle     NVARCHAR(25)  NOT NULL,
    start_date        DATE          NOT NULL,
    end_date          DATE          NULL,
    is_active         BIT           NOT NULL CONSTRAINT df_subscriptions_is_active DEFAULT 1,
    payment_method_id INT           NOT NULL,
    CONSTRAINT pk_subscriptions PRIMARY KEY (subscription_id),
    CONSTRAINT fk_subscriptions_payment_method_id FOREIGN KEY (payment_method_id) REFERENCES payment_methods (payment_method_id)
);
GO

CREATE TABLE expenses
(
    expense_id        INT IDENTITY(1,1) NOT NULL,
    expense_name      NVARCHAR(50)  NOT NULL,
    [provider]        NVARCHAR(50)  NOT NULL,
    purpose           NVARCHAR(250) NULL,
    cost              DECIMAL(19,4) NOT NULL,
    purchase_date     DATE          NOT NULL,
    subscription_id   INT           NULL,
    payment_method_id INT           NOT NULL,
    CONSTRAINT pk_expenses PRIMARY KEY (expense_id),
    CONSTRAINT fk_expenses_subscription_id   FOREIGN KEY (subscription_id)   REFERENCES subscriptions (subscription_id),
    CONSTRAINT fk_expenses_payment_method_id FOREIGN KEY (payment_method_id) REFERENCES payment_methods (payment_method_id)
);
GO

CREATE INDEX ix_expenses_purchase_date ON expenses (purchase_date);
GO

CREATE TABLE broker_events
(
    broker_event_id BIGINT IDENTITY(1,1) NOT NULL,
    alpaca_order_id NVARCHAR(128) NULL,
    client_order_id NVARCHAR(128) NULL,
    execution_id    NVARCHAR(128) NULL,
    event_type      NVARCHAR(30)  NOT NULL,
    ticker          NVARCHAR(10)  NULL,
    event_at        DATETIME2     NULL,
    received_at     DATETIME2     NOT NULL CONSTRAINT df_broker_events_received_at DEFAULT SYSUTCDATETIME(),
    raw_json        NVARCHAR(MAX) NOT NULL,
    CONSTRAINT pk_broker_events PRIMARY KEY (broker_event_id)
);
GO

CREATE INDEX ix_broker_events_alpaca_order_id ON broker_events (alpaca_order_id);
CREATE INDEX ix_broker_events_execution_id ON broker_events (execution_id);
CREATE INDEX ix_broker_events_received_at ON broker_events (received_at);
GO

CREATE TABLE account_activities
(
    account_activity_id BIGINT IDENTITY(1,1) NOT NULL,
    alpaca_activity_id  NVARCHAR(128) NOT NULL,
    alpaca_order_id     NVARCHAR(128) NULL,
    activity_type       NVARCHAR(10)  NOT NULL,
    activity_at         DATETIME2     NOT NULL,
    ticker              NVARCHAR(10)  NULL,
    side                NVARCHAR(5)   NULL,
    quantity            DECIMAL(19,4) NULL,  -- not INT: a reverse split can leave fractional shares
    price               DECIMAL(19,4) NULL,
    net_amount          DECIMAL(19,4) NULL,
    loaded_at           DATETIME2     NOT NULL CONSTRAINT df_account_activities_loaded_at DEFAULT SYSUTCDATETIME(),
    raw_json            NVARCHAR(MAX) NOT NULL,
    CONSTRAINT pk_account_activities PRIMARY KEY (account_activity_id),

    CONSTRAINT uq_account_activities_alpaca_activity_id UNIQUE (alpaca_activity_id)
);
GO

CREATE INDEX ix_account_activities_alpaca_order_id ON account_activities (alpaca_order_id);
CREATE INDEX ix_account_activities_activity_at ON account_activities (activity_at);
GO

CREATE TABLE audit_log
(
    audit_id          INT IDENTITY(1,1) NOT NULL,
    audit_date        DATE          NOT NULL,
    audit_type        NVARCHAR(20)  NOT NULL,
    run_at            DATETIME2     NOT NULL CONSTRAINT df_audit_log_run_at DEFAULT SYSUTCDATETIME(),
    fills_at_alpaca   INT           NOT NULL,
    fills_in_db       INT           NOT NULL,
    missing_in_db     INT           NOT NULL,
    missing_at_alpaca INT           NOT NULL,
    [status]          NVARCHAR(10)  NOT NULL,
    notes             NVARCHAR(MAX) NULL,
    resolved_at       DATETIME2     NULL,
    CONSTRAINT pk_audit_log PRIMARY KEY (audit_id),
    CONSTRAINT ck_audit_log_audit_type CHECK (audit_type IN ('end_of_day', 'catch_up')),
    CONSTRAINT ck_audit_log_status CHECK ([status] IN ('pass', 'fail'))
);
GO

CREATE INDEX ix_audit_log_audit_date ON audit_log (audit_date);
GO

CREATE TABLE health_status
(
    health_status_id     INT IDENTITY(1,1) NOT NULL,
    recorded_at          DATETIME2    NOT NULL CONSTRAINT df_health_status_recorded_at DEFAULT SYSUTCDATETIME(),
    cpu_pct              DECIMAL(5,2) NOT NULL,
    memory_pct           DECIMAL(5,2) NOT NULL,
    disk_pct             DECIMAL(5,2) NOT NULL,
    cycle_seconds        DECIMAL(7,2) NULL,
    tickers_checked      INT          NULL,
    tickers_bad          INT          NULL,
    api_calls            INT          NOT NULL,
    rate_limit_remaining INT          NOT NULL,
    errors               INT          NOT NULL,
    db_used_mb           INT          NOT NULL,
    db_max_mb            INT          NOT NULL,
    CONSTRAINT pk_health_status PRIMARY KEY (health_status_id)
);
GO

CREATE INDEX ix_health_status_recorded_at ON health_status (recorded_at);
GO

-- 'swing' so the end-of-day job never closes a position the bot didn't open.
INSERT INTO strategies (strategy, time_frame, default_holding_type, budget, is_active)
VALUES
    ('manual',  'none', 'swing', 0, 0),
    ('unknown', 'none', 'swing', 0, 0);
GO
