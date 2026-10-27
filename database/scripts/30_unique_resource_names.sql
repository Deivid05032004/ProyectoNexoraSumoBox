USE UTA_SUMO_ROBOTICS_CUP;
GO

IF EXISTS (SELECT 1 FROM dbo.Teams WHERE NameLookupHash IS NULL)
    THROW 51000, 'Teams.NameLookupHash requiere completar el backfill antes de crear la restricción.', 1;
IF EXISTS (SELECT 1 FROM dbo.Robots WHERE NameLookupHash IS NULL)
    THROW 51001, 'Robots.NameLookupHash requiere completar el backfill antes de crear la restricción.', 1;
GO

ALTER TABLE dbo.Teams ALTER COLUMN NameLookupHash VARCHAR(64) NOT NULL;
GO
ALTER TABLE dbo.Robots ALTER COLUMN NameLookupHash VARCHAR(64) NOT NULL;
GO
CREATE UNIQUE INDEX UX_Teams_NameLookupHash ON dbo.Teams(NameLookupHash);
GO
CREATE UNIQUE INDEX UX_Robots_NameLookupHash ON dbo.Robots(NameLookupHash);
GO
