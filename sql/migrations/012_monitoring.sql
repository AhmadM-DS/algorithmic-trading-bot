SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

INSERT INTO skip_reasons (skip_reason_id, code, [description], [priority])
VALUES (25, 'database_write_failed', 'A database save is failing', 35);
GO

-- A reading that fails is saved as NULL; the counts stay required (0 when idle).
-- process has no default: every writer must say which process it is.
ALTER TABLE health_status ALTER COLUMN cpu_pct              DECIMAL(5,2) NULL;
ALTER TABLE health_status ALTER COLUMN memory_pct           DECIMAL(5,2) NULL;
ALTER TABLE health_status ALTER COLUMN disk_pct             DECIMAL(5,2) NULL;
ALTER TABLE health_status ALTER COLUMN rate_limit_remaining INT          NULL;
ALTER TABLE health_status ALTER COLUMN db_used_mb           INT          NULL;
ALTER TABLE health_status ALTER COLUMN db_max_mb            INT          NULL;
ALTER TABLE health_status ADD process NVARCHAR(20) NOT NULL
    CONSTRAINT ck_health_status_process CHECK (process IN ('bot', 'fill_stream'));
GO

CREATE INDEX ix_health_status_process_recorded_at ON health_status (process, recorded_at);
GO

-- The long-term archive of health_status: raw rows are deleted after the rollup, so this is the only copy.
CREATE TABLE health_status_hourly
(
    health_status_hourly_id  INT IDENTITY(1,1) NOT NULL,
    process                  NVARCHAR(20) NOT NULL,
    hour_start               DATETIME2(0) NOT NULL,
    beats                    INT          NOT NULL,
    cycles                   INT          NOT NULL,
    cpu_pct_min              DECIMAL(5,2) NULL,
    cpu_pct_avg              DECIMAL(5,2) NULL,
    cpu_pct_max              DECIMAL(5,2) NULL,
    memory_pct_min           DECIMAL(5,2) NULL,
    memory_pct_avg           DECIMAL(5,2) NULL,
    memory_pct_max           DECIMAL(5,2) NULL,
    disk_pct_min             DECIMAL(5,2) NULL,
    disk_pct_avg             DECIMAL(5,2) NULL,
    disk_pct_max             DECIMAL(5,2) NULL,
    cycle_seconds_min        DECIMAL(7,2) NULL,
    cycle_seconds_avg        DECIMAL(7,2) NULL,
    cycle_seconds_max        DECIMAL(7,2) NULL,
    api_calls_max            INT          NOT NULL,
    rate_limit_remaining_min INT          NULL,
    errors                   INT          NOT NULL,
    db_used_mb_max           INT          NULL,
    db_max_mb                INT          NULL,
    rolled_up_at             DATETIME2    NOT NULL CONSTRAINT df_health_status_hourly_rolled_up_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_health_status_hourly PRIMARY KEY (health_status_hourly_id),
    CONSTRAINT uq_health_status_hourly_process_hour UNIQUE (process, hour_start),
    CONSTRAINT ck_health_status_hourly_process CHECK (process IN ('bot', 'fill_stream')),
    CONSTRAINT ck_health_status_hourly_hour_start CHECK (DATEPART(minute, hour_start) = 0
                                                         AND DATEPART(second, hour_start) = 0),
    CONSTRAINT ck_health_status_hourly_beats CHECK (beats > 0),
    CONSTRAINT ck_health_status_hourly_cycles CHECK (cycles BETWEEN 0 AND beats)
);
GO

GRANT INSERT ON dbo.health_status_hourly TO bot_role;
DENY UPDATE, DELETE ON dbo.health_status_hourly TO bot_role;
GO

GRANT SELECT ON dbo.health_status (process) TO claude_reader_role;
GRANT SELECT ON dbo.health_status_hourly (health_status_hourly_id, process, hour_start, beats, cycles, cpu_pct_min,
    cpu_pct_avg, cpu_pct_max, memory_pct_min, memory_pct_avg, memory_pct_max, disk_pct_min, disk_pct_avg,
    disk_pct_max, cycle_seconds_min, cycle_seconds_avg, cycle_seconds_max, api_calls_max, rate_limit_remaining_min,
    errors, db_used_mb_max, db_max_mb, rolled_up_at) TO claude_reader_role;
GO
