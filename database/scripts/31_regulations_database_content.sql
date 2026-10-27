USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Nullable during the transactional backfill performed by migrate.py. */
IF COL_LENGTH('dbo.EventRegulations','FileContent') IS NULL
    ALTER TABLE dbo.EventRegulations ADD FileContent VARBINARY(MAX) NULL;
GO
