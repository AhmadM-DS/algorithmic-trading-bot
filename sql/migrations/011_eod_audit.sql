SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

INSERT INTO skip_reasons (skip_reason_id, code, [description], [priority])
VALUES (24, 'audit_failure', 'An audit found this ticker''s records wrong', 45);
GO

ALTER TABLE audit_log DROP CONSTRAINT ck_audit_log_status;
ALTER TABLE audit_log ALTER COLUMN fills_at_alpaca   INT NULL;
ALTER TABLE audit_log ALTER COLUMN fills_in_db       INT NULL;
ALTER TABLE audit_log ALTER COLUMN missing_in_db     INT NULL;
ALTER TABLE audit_log ALTER COLUMN missing_at_alpaca INT NULL;
ALTER TABLE audit_log ADD
    not_run_reason      NVARCHAR(250) NULL,
    catch_up_fills      INT           NULL,
    audit_fills         INT           NULL,
    price_mismatches    INT           NULL,
    quantity_mismatches INT           NULL,
    share_mismatches    INT           NULL,
    alpaca_cash         DECIMAL(19,4) NULL,
    expected_cash       DECIMAL(19,4) NULL;
GO

-- A run that couldn't happen has a reason and nothing it would have counted; every other run has every count.
-- share_mismatches and the cash pair are left out of the rule: only the last run of a batch checks them.
ALTER TABLE audit_log ADD
    CONSTRAINT ck_audit_log_status CHECK ([status] IN ('pass', 'fail', 'not_run')),
    CONSTRAINT ck_audit_log_not_run CHECK (
        ([status] = 'not_run' AND not_run_reason IS NOT NULL
            AND fills_at_alpaca IS NULL AND fills_in_db IS NULL AND missing_in_db IS NULL
            AND missing_at_alpaca IS NULL AND catch_up_fills IS NULL AND audit_fills IS NULL
            AND price_mismatches IS NULL AND quantity_mismatches IS NULL AND share_mismatches IS NULL
            AND alpaca_cash IS NULL)
        OR
        ([status] <> 'not_run' AND not_run_reason IS NULL
            AND fills_at_alpaca IS NOT NULL AND fills_in_db IS NOT NULL AND missing_in_db IS NOT NULL
            AND missing_at_alpaca IS NOT NULL AND catch_up_fills IS NOT NULL AND audit_fills IS NOT NULL
            AND price_mismatches IS NOT NULL AND quantity_mismatches IS NOT NULL)
    ),
    CONSTRAINT ck_audit_log_cash CHECK (
        (alpaca_cash IS NULL AND expected_cash IS NULL) OR (alpaca_cash IS NOT NULL AND expected_cash IS NOT NULL)
    ),
    CONSTRAINT ck_audit_log_resolved CHECK (resolved_at IS NULL OR [status] = 'fail');
GO

CREATE TABLE audit_failures
(
    audit_failure_id INT IDENTITY(1,1) NOT NULL,
    audit_id         INT           NOT NULL,
    kind             NVARCHAR(30)  NOT NULL,
    ticker           NVARCHAR(10)  NULL,
    alpaca_fill_id   NVARCHAR(128) NULL,
    details          NVARCHAR(MAX) NULL,
    CONSTRAINT pk_audit_failures PRIMARY KEY (audit_failure_id),
    CONSTRAINT fk_audit_failures_audit_id FOREIGN KEY (audit_id) REFERENCES audit_log (audit_id),
    CONSTRAINT ck_audit_failures_kind CHECK (kind IN ('missing_in_db', 'missing_at_alpaca', 'price_mismatch',
        'quantity_mismatch', 'order_fill_mismatch', 'share_mismatch', 'cash', 'unreadable_activity',
        'untracked_symbol')),
    CONSTRAINT ck_audit_failures_ticker CHECK (
        (kind IN ('cash', 'unreadable_activity', 'untracked_symbol') AND ticker IS NULL)
        OR (kind NOT IN ('cash', 'unreadable_activity', 'untracked_symbol') AND ticker IS NOT NULL)
    )
);
GO

CREATE INDEX ix_audit_failures_audit_id ON audit_failures (audit_id);
CREATE INDEX ix_audit_failures_ticker ON audit_failures (ticker);
GO

CREATE TABLE cash_adjustments
(
    cash_adjustment_id INT IDENTITY(1,1) NOT NULL,
    amount             DECIMAL(19,4) NOT NULL,
    effective_date     DATE          NOT NULL,
    reason             NVARCHAR(30)  NOT NULL,
    note               NVARCHAR(250) NULL,
    created_at         DATETIME2     NOT NULL CONSTRAINT df_cash_adjustments_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_cash_adjustments PRIMARY KEY (cash_adjustment_id),
    CONSTRAINT ck_cash_adjustments_amount CHECK (amount <> 0),
    CONSTRAINT ck_cash_adjustments_reason CHECK (reason IN ('deposit', 'withdrawal', 'fee', 'dividend', 'interest',
        'correction', 'other'))
);
GO

REVOKE UPDATE ON dbo.audit_log FROM bot_role;
GRANT UPDATE (resolved_at) ON dbo.audit_log TO bot_role;
GRANT INSERT ON dbo.audit_failures TO bot_role;
DENY UPDATE, DELETE ON dbo.audit_failures TO bot_role;
DENY INSERT, UPDATE, DELETE ON dbo.cash_adjustments TO bot_role;
GO

GRANT SELECT ON dbo.audit_log (not_run_reason, catch_up_fills, audit_fills, price_mismatches, quantity_mismatches,
    share_mismatches) TO claude_reader_role;
GRANT SELECT ON dbo.audit_failures (audit_failure_id, audit_id, kind, ticker, alpaca_fill_id) TO claude_reader_role;
GRANT SELECT ON dbo.cash_adjustments (cash_adjustment_id, effective_date, reason, note, created_at)
    TO claude_reader_role;
GO
