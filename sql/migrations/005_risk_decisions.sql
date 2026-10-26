-- Triggers keep the ANSI_NULLS / QUOTED_IDENTIFIER settings they were created with.
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

CREATE TABLE skip_reasons
(
    skip_reason_id INT           NOT NULL,
    code           NVARCHAR(50)  NOT NULL,
    [description]  NVARCHAR(250) NOT NULL,
    [priority]     INT           NOT NULL,
    CONSTRAINT pk_skip_reasons PRIMARY KEY (skip_reason_id),
    CONSTRAINT uq_skip_reasons_code UNIQUE (code),
    CONSTRAINT uq_skip_reasons_priority UNIQUE ([priority])
);
GO

-- Steps of 10 so later codes (E2's checks, the ML model) fit between without renumbering.
INSERT INTO skip_reasons (skip_reason_id, code, [description], [priority])
VALUES
    (1,  'shadow',                   'Strategy is in shadow mode',                  10),
    (2,  'strategy_off',             'Strategy is switched off',                    20),
    (3,  'kill_switch',              'Account lost too much today',                 30),
    (4,  'audit_mismatch',           'Database and Alpaca disagree',                40),
    (5,  'drawdown_limit',           'Strategy fell too far from its peak',         50),
    (6,  'daily_halt',               'Strategy hit today''s limit',                 60),
    (7,  'max_leverage',             'Would need borrowed money',                   70),
    (8,  'buying_power',             'More than Alpaca''s buying power',            80),
    (9,  'budget_exhausted',         'No room left in the strategy''s budget',      90),
    (10, 'max_positions',            'Account holds the maximum positions',         100),
    (11, 'max_per_ticker',           'Too much money in one ticker',                110),
    (12, 'max_positions_per_ticker', 'Strategy can''t stack more of this ticker',   120),
    (13, 'cooldown',                 'Still waiting after the last exit',           130),
    (14, 'zero_quantity',            'One share costs more than the slice',         140),
    (15, 'max_order_size',           'Single order too large (likely a bug)',       150),
    (16, 'nothing_to_sell',          'Sell with no shares held',                    500);
GO

CREATE TABLE signal_skip_reasons
(
    signal_id      INT NOT NULL,
    skip_reason_id INT NOT NULL,
    CONSTRAINT pk_signal_skip_reasons PRIMARY KEY (signal_id, skip_reason_id),
    CONSTRAINT fk_signal_skip_reasons_signal_id      FOREIGN KEY (signal_id)      REFERENCES signals (signal_id),
    CONSTRAINT fk_signal_skip_reasons_skip_reason_id FOREIGN KEY (skip_reason_id) REFERENCES skip_reasons (skip_reason_id)
);
GO

CREATE INDEX ix_signal_skip_reasons_skip_reason_id ON signal_skip_reasons (skip_reason_id);
GO

ALTER TABLE signals DROP CONSTRAINT ck_signals_taken_skip_reason;
ALTER TABLE signals DROP COLUMN skip_reason;
ALTER TABLE signals ADD primary_skip_reason_id INT NULL
    CONSTRAINT fk_signals_primary_skip_reason_id REFERENCES skip_reasons (skip_reason_id);
GO

ALTER TABLE signals ADD CONSTRAINT ck_signals_taken_primary_skip_reason CHECK (
    (taken = 1 AND primary_skip_reason_id IS NULL) OR (taken = 0 AND primary_skip_reason_id IS NOT NULL)
);
GO

CREATE TABLE risk_decisions
(
    risk_decision_id  BIGINT IDENTITY(1,1) NOT NULL,
    signal_id         INT           NOT NULL,
    sizer             NVARCHAR(50)  NOT NULL,
    sized_quantity    INT           NOT NULL,
    equity            DECIMAL(19,4) NOT NULL,
    buying_power      DECIMAL(19,4) NOT NULL,
    trading_budget    DECIMAL(19,4) NOT NULL,
    account_exposure  DECIMAL(19,4) NOT NULL,
    strategy_exposure DECIMAL(19,4) NOT NULL,
    ticker_exposure   DECIMAL(19,4) NOT NULL,
    open_positions    INT           NOT NULL,
    shares_held       INT           NOT NULL,
    broker_shares     INT           NOT NULL,
    CONSTRAINT pk_risk_decisions PRIMARY KEY (risk_decision_id),
    CONSTRAINT fk_risk_decisions_signal_id FOREIGN KEY (signal_id) REFERENCES signals (signal_id),
    CONSTRAINT uq_risk_decisions_signal_id UNIQUE (signal_id),
    CONSTRAINT ck_risk_decisions_sized_quantity CHECK (sized_quantity >= 0)
);
GO

-- proposed is NULL when the provider gave nothing usable (NaN in Python can't be stored).
CREATE TABLE risk_decision_parameters
(
    risk_decision_parameter_id BIGINT IDENTITY(1,1) NOT NULL,
    risk_decision_id           BIGINT       NOT NULL,
    [name]                     NVARCHAR(50) NOT NULL,
    [provider]                 NVARCHAR(50) NOT NULL,
    proposed                   FLOAT        NULL,
    used                       FLOAT        NOT NULL,
    clamped                    BIT          NOT NULL,
    rate_limited               BIT          NOT NULL,
    fell_back                  BIT          NOT NULL,
    CONSTRAINT pk_risk_decision_parameters PRIMARY KEY (risk_decision_parameter_id),
    CONSTRAINT fk_risk_decision_parameters_risk_decision_id FOREIGN KEY (risk_decision_id) REFERENCES risk_decisions (risk_decision_id),
    CONSTRAINT uq_risk_decision_parameters_risk_decision_id_name UNIQUE (risk_decision_id, [name]),

    CONSTRAINT ck_risk_decision_parameters_fell_back CHECK (
        fell_back = 0 OR (proposed IS NULL AND clamped = 0 AND rate_limited = 0)
    )
);
GO

ALTER TABLE strategies ADD budget_set_at DATETIME2 NOT NULL
    CONSTRAINT df_strategies_budget_set_at DEFAULT SYSUTCDATETIME();
GO

CREATE TRIGGER trg_strategies_budget_set_at ON strategies
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT UPDATE(budget) RETURN;

    UPDATE s
    SET budget_set_at = SYSUTCDATETIME()
    FROM strategies s
    JOIN inserted i ON i.strategy_id = s.strategy_id
    JOIN deleted d ON d.strategy_id = i.strategy_id
    WHERE i.budget <> d.budget;

    INSERT INTO bot_events (event_type, details, strategy_id)
    SELECT 'budget_changed', CONCAT('Budget changed from ', d.budget, ' to ', i.budget), i.strategy_id
    FROM inserted i
    JOIN deleted d ON d.strategy_id = i.strategy_id
    WHERE i.budget <> d.budget;
END;
GO

GRANT INSERT ON dbo.signal_skip_reasons      TO bot_role;
GRANT INSERT ON dbo.risk_decisions           TO bot_role;
GRANT INSERT ON dbo.risk_decision_parameters TO bot_role;
GO

DENY UPDATE, DELETE ON dbo.signal_skip_reasons      TO bot_role;
DENY UPDATE, DELETE ON dbo.risk_decisions           TO bot_role;
DENY UPDATE, DELETE ON dbo.risk_decision_parameters TO bot_role;
GO
