USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Keyed name fingerprints allow exact duplicate checks without exposing names
   stored with randomized application-level encryption. */
IF COL_LENGTH('dbo.Teams','NameLookupHash') IS NULL
    ALTER TABLE dbo.Teams ADD NameLookupHash VARCHAR(64) NULL;
GO
IF COL_LENGTH('dbo.Robots','NameLookupHash') IS NULL
    ALTER TABLE dbo.Robots ADD NameLookupHash VARCHAR(64) NULL;
GO
