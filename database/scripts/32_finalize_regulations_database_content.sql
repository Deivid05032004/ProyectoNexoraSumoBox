USE UTA_SUMO_ROBOTICS_CUP;
GO

IF EXISTS (SELECT 1 FROM dbo.EventRegulations WHERE FileContent IS NULL)
    THROW 51020, 'No se puede finalizar el almacenamiento: hay reglamentos sin FileContent.', 1;
GO

IF EXISTS (SELECT 1 FROM sys.key_constraints
           WHERE parent_object_id=OBJECT_ID('dbo.EventRegulations')
             AND name='UQ_EventRegulations_StorageKey')
    ALTER TABLE dbo.EventRegulations DROP CONSTRAINT UQ_EventRegulations_StorageKey;
GO

IF COL_LENGTH('dbo.EventRegulations','StorageKey') IS NOT NULL
    ALTER TABLE dbo.EventRegulations DROP COLUMN StorageKey;
GO

ALTER TABLE dbo.EventRegulations ALTER COLUMN FileContent VARBINARY(MAX) NOT NULL;
GO
