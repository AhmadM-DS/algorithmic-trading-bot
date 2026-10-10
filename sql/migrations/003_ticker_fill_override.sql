ALTER TABLE tickers ADD fill_override BIT NULL;
GO

DENY UPDATE ON dbo.tickers (fill_override) TO bot_role;
GO
