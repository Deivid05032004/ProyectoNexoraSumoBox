USE UTA_SUMO_ROBOTICS_CUP;
GO

/* A robot has one owning team. Infer existing ownership from registrations;
   stop before changing constraints if legacy data cannot be mapped safely. */
IF COL_LENGTH('dbo.Robots','TeamId') IS NULL
    ALTER TABLE dbo.Robots ADD TeamId INT NULL;
GO

IF EXISTS (
    SELECT b.RobotId
    FROM dbo.Robots b
    LEFT JOIN dbo.Registrations r ON r.RobotId=b.RobotId
    GROUP BY b.RobotId
    HAVING COUNT(DISTINCT r.TeamId)<>1
)
    THROW 51042, 'No se puede migrar: hay robots sin inscripcion o asociados a mas de un equipo. Asigne un unico equipo antes de reintentar.', 1;
GO

UPDATE b
SET TeamId=ownership.TeamId
FROM dbo.Robots b
CROSS APPLY (
    SELECT MIN(r.TeamId) AS TeamId
    FROM dbo.Registrations r
    WHERE r.RobotId=b.RobotId
) ownership
WHERE b.TeamId IS NULL;
GO

IF EXISTS (SELECT 1 FROM dbo.Robots WHERE TeamId IS NULL)
    THROW 51043, 'No se pudo determinar el equipo de todos los robots existentes.', 1;
GO

IF EXISTS (
    SELECT 1 FROM dbo.Robots
    GROUP BY TeamId,NameLookupHash
    HAVING COUNT_BIG(*)>1
)
    THROW 51044, 'Hay robots con el mismo nombre dentro de un equipo. Resuelva los duplicados antes de migrar.', 1;
GO

IF EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Robots')
           AND name='UX_Robots_NameLookupHash')
    DROP INDEX UX_Robots_NameLookupHash ON dbo.Robots;
GO

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.Robots')
           AND name='TeamId' AND is_nullable=1)
    ALTER TABLE dbo.Robots ALTER COLUMN TeamId INT NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_Robots_Team')
    ALTER TABLE dbo.Robots ADD CONSTRAINT FK_Robots_Team
        FOREIGN KEY(TeamId) REFERENCES dbo.Teams(TeamId);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Robots')
               AND name='UX_Robots_Team_NameLookupHash')
    CREATE UNIQUE INDEX UX_Robots_Team_NameLookupHash
        ON dbo.Robots(TeamId,NameLookupHash);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Robots')
               AND name='IX_Robots_TeamId')
    CREATE INDEX IX_Robots_TeamId ON dbo.Robots(TeamId);
GO
