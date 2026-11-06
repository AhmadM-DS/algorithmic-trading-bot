ALTER TABLE orders ADD exit_reason NVARCHAR(50) NULL
    CONSTRAINT ck_orders_exit_reason CHECK (exit_reason IN
        ('signal', 'take_profit', 'stop_loss', 'end_of_day', 'kill_switch', 'manual', 'liquidation'));
GO

ALTER TABLE orders ADD CONSTRAINT ck_orders_exit_reason_sells_only CHECK (side = 'sell' OR exit_reason IS NULL);
GO
