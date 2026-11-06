ALTER TABLE risk_decisions ADD
    strategy_daily_pnl DECIMAL(19, 4) NOT NULL,
    strategy_drawdown DECIMAL(19, 4) NOT NULL,
    account_daily_change DECIMAL(19, 4) NOT NULL,
    start_equity DECIMAL(19, 4) NOT NULL,

    CONSTRAINT ck_risk_decisions_strategy_drawdown CHECK (strategy_drawdown >= 0);
GO
