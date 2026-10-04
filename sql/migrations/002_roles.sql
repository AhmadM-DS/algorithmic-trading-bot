CREATE ROLE bot_role;
CREATE ROLE report_role;
GO

GRANT SELECT ON SCHEMA::dbo TO bot_role;

GRANT INSERT ON dbo.strategies         TO bot_role;
GRANT INSERT ON dbo.tickers            TO bot_role;
GRANT INSERT ON dbo.signals            TO bot_role;
GRANT INSERT ON dbo.signal_features    TO bot_role;
GRANT INSERT ON dbo.positions          TO bot_role;
GRANT INSERT ON dbo.orders             TO bot_role;
GRANT INSERT ON dbo.trades             TO bot_role;
GRANT INSERT ON dbo.watchlist_history  TO bot_role;
GRANT INSERT ON dbo.data_health        TO bot_role;
GRANT INSERT ON dbo.bot_events         TO bot_role;
GRANT INSERT ON dbo.expenses           TO bot_role;
GRANT INSERT ON dbo.broker_events      TO bot_role;
GRANT INSERT ON dbo.account_activities TO bot_role;
GRANT INSERT ON dbo.audit_log          TO bot_role;
GRANT INSERT ON dbo.health_status      TO bot_role;

GRANT UPDATE ON dbo.tickers   TO bot_role;
GRANT UPDATE ON dbo.signals   TO bot_role;
GRANT UPDATE ON dbo.positions TO bot_role;
GRANT UPDATE ON dbo.orders    TO bot_role;
GRANT UPDATE ON dbo.audit_log TO bot_role;
GRANT UPDATE ON dbo.expenses  TO bot_role;

GRANT DELETE ON dbo.health_status TO bot_role;

DENY UPDATE, DELETE ON dbo.trades             TO bot_role;
DENY UPDATE, DELETE ON dbo.broker_events      TO bot_role;
DENY UPDATE, DELETE ON dbo.account_activities TO bot_role;
GO

GRANT SELECT ON SCHEMA::report TO report_role;
GO
