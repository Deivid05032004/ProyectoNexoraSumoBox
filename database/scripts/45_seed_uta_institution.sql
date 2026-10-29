/* Public participant registration needs at least one selectable institution.
   Keep this additive and idempotent for both fresh and already migrated DBs. */
USE UTA_SUMO_ROBOTICS_CUP;
GO

IF NOT EXISTS (
    SELECT 1
    FROM dbo.Institutions
    WHERE Name = N'UNIVERSIDAD TÉCNICA DE AMBATO'
)
BEGIN
    INSERT INTO dbo.Institutions (Name)
    VALUES (N'UNIVERSIDAD TÉCNICA DE AMBATO');
END;
GO
