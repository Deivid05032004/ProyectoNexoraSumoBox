USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Per-event category availability and roster rules. Defaults preserve the
   former API's broad 1..30 roster range; event 2026's Mini Sumo rules are
   explicitly seeded below. Existing registrations and tariffs are untouched. */
IF OBJECT_ID('dbo.EventCategories','U') IS NULL
BEGIN
    CREATE TABLE dbo.EventCategories (
        EventId INT NOT NULL,
        CategoryId INT NOT NULL,
        IsActive BIT NOT NULL CONSTRAINT DF_EventCategories_IsActive DEFAULT 1,
        MinParticipants TINYINT NOT NULL CONSTRAINT DF_EventCategories_MinParticipants DEFAULT 1,
        MaxParticipants TINYINT NOT NULL CONSTRAINT DF_EventCategories_MaxParticipants DEFAULT 30,
        MinCoaches TINYINT NOT NULL CONSTRAINT DF_EventCategories_MinCoaches DEFAULT 0,
        MaxCoaches TINYINT NOT NULL CONSTRAINT DF_EventCategories_MaxCoaches DEFAULT 30,
        MaxRegistrations INT NULL,
        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_EventCategories_CreatedAt DEFAULT SYSUTCDATETIME(),
        UpdatedAt DATETIME2 NOT NULL CONSTRAINT DF_EventCategories_UpdatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_EventCategories PRIMARY KEY(EventId,CategoryId),
        CONSTRAINT FK_EventCategories_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_EventCategories_Category FOREIGN KEY(CategoryId) REFERENCES dbo.Categories(CategoryId),
        CONSTRAINT CK_EventCategories_Participants CHECK(MinParticipants BETWEEN 1 AND MaxParticipants AND MaxParticipants<=30),
        CONSTRAINT CK_EventCategories_Coaches CHECK(MinCoaches<=MaxCoaches AND MaxCoaches<=30),
        CONSTRAINT CK_EventCategories_MaxRegistrations CHECK(MaxRegistrations IS NULL OR MaxRegistrations>0)
    );
    CREATE INDEX IX_EventCategories_Public ON dbo.EventCategories(EventId,IsActive,CategoryId)
      INCLUDE(MinParticipants,MaxParticipants,MinCoaches,MaxCoaches,MaxRegistrations);
END;
GO

/* The prior schema reserved three positions. Keep the byte column and widen
   only its bound so configurable rosters up to 30 can be represented. */
IF EXISTS (SELECT 1 FROM sys.check_constraints
           WHERE name='CK_RegistrationParticipants_Position'
             AND parent_object_id=OBJECT_ID('dbo.RegistrationParticipants'))
    ALTER TABLE dbo.RegistrationParticipants DROP CONSTRAINT CK_RegistrationParticipants_Position;
ALTER TABLE dbo.RegistrationParticipants
    ADD CONSTRAINT CK_RegistrationParticipants_Position
    CHECK (RegistrationPosition IS NULL OR RegistrationPosition BETWEEN 1 AND 30);
GO

/* Attach all categories already used by this event's tariffs or registrations. */
INSERT INTO dbo.EventCategories(EventId,CategoryId)
SELECT source.EventId,source.CategoryId
FROM (
    SELECT EventId,CategoryId FROM dbo.Tariffs
    UNION
    SELECT EventId,CategoryId FROM dbo.Registrations
) AS source
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.EventCategories ec
    WHERE ec.EventId=source.EventId AND ec.CategoryId=source.CategoryId
);
GO

/* Preserve the official 2026 category rule in data, not application code. */
UPDATE ec SET MinParticipants=2,MaxParticipants=2,MinCoaches=0,MaxCoaches=0,
  UpdatedAt=SYSUTCDATETIME()
FROM dbo.EventCategories ec
JOIN dbo.Events e ON e.EventId=ec.EventId
JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId
WHERE e.Name=N'UTA SUMO ROBOTICS CUP 2026' AND e.EditionYear=2026
  AND c.Name=N'MINI SUMO AMATEUR RC'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.Registrations r WHERE r.EventId=ec.EventId AND r.CategoryId=ec.CategoryId
  );
GO
