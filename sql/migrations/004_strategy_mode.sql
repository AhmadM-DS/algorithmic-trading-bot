ALTER TABLE strategies ADD mode NVARCHAR(10) NULL;
GO

UPDATE strategies SET mode = CASE WHEN is_active = 1 THEN 'live' ELSE 'off' END;
GO

ALTER TABLE strategies ALTER COLUMN mode NVARCHAR(10) NOT NULL;
GO

ALTER TABLE strategies ADD CONSTRAINT ck_strategies_mode CHECK (mode IN ('off', 'shadow', 'live'));
GO

ALTER TABLE strategies DROP CONSTRAINT df_strategies_is_active;
GO

ALTER TABLE strategies DROP COLUMN is_active;
GO
