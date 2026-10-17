USE UTA_SUMO_ROBOTICS_CUP;
GO

-- Collapse legacy reviewer/treasury roles into the requested three-role model.
-- REVIEWER becomes operational EVENT_MANAGER; TREASURY becomes ADMIN because
-- the new model has no finance-only role. Review assignments before deployment.
IF NOT EXISTS (SELECT 1 FROM dbo.Roles WHERE Code='EVENT_MANAGER')
    INSERT dbo.Roles(Code,Name) VALUES ('EVENT_MANAGER',N'Gestor de eventos');
DECLARE @admin INT=(SELECT RoleId FROM dbo.Roles WHERE Code='ADMIN');
DECLARE @event_manager INT=(SELECT RoleId FROM dbo.Roles WHERE Code='EVENT_MANAGER');
IF @admin IS NULL OR @event_manager IS NULL
    THROW 51010, 'ADMIN y EVENT_MANAGER deben existir.', 1;
UPDATE u SET RoleId=@event_manager FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId WHERE r.Code='REVIEWER';
UPDATE u SET RoleId=@admin FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId WHERE r.Code='TREASURY';
IF EXISTS (SELECT 1 FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId
           WHERE r.Code NOT IN ('ADMIN','EVENT_MANAGER','PARTICIPANT'))
    THROW 51011, 'Hay usuarios con roles no reconocidos; reasígnelos antes de esta migración.', 1;
DELETE FROM dbo.Roles WHERE Code NOT IN ('ADMIN','EVENT_MANAGER','PARTICIPANT');

IF COL_LENGTH('dbo.Events','CompetitionStatus') IS NULL
BEGIN
    ALTER TABLE dbo.Events ADD CompetitionStatus VARCHAR(20) NOT NULL
        CONSTRAINT DF_Events_CompetitionStatus DEFAULT 'DRAFT';
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_Events_CompetitionStatus')
    ALTER TABLE dbo.Events ADD CONSTRAINT CK_Events_CompetitionStatus
        CHECK (CompetitionStatus IN ('DRAFT','SCHEDULED','LIVE','PAUSED','FINISHED','CANCELLED'));
GO

IF OBJECT_ID('dbo.CompetitionRounds','U') IS NULL
BEGIN
    CREATE TABLE dbo.CompetitionRounds(
        RoundId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CompetitionRounds PRIMARY KEY,
        EventId INT NOT NULL, CategoryId INT NOT NULL, RoundNumber INT NOT NULL,
        Name NVARCHAR(120) NOT NULL, RoundStatus VARCHAR(20) NOT NULL CONSTRAINT DF_Rounds_Status DEFAULT 'SCHEDULED',
        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_Rounds_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_Rounds_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_Rounds_Category FOREIGN KEY(CategoryId) REFERENCES dbo.Categories(CategoryId),
        CONSTRAINT UQ_Rounds_EventCategoryNumber UNIQUE(EventId,CategoryId,RoundNumber),
        CONSTRAINT CK_Rounds_Status CHECK(RoundStatus IN ('SCHEDULED','LIVE','FINISHED','CANCELLED')),
        CONSTRAINT CK_Rounds_Number CHECK(RoundNumber>0)
    );
END;
IF OBJECT_ID('dbo.CompetitionMatches','U') IS NULL
BEGIN
    CREATE TABLE dbo.CompetitionMatches(
        MatchId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CompetitionMatches PRIMARY KEY,
        RoundId INT NOT NULL, MatchNumber INT NOT NULL,
        MatchStatus VARCHAR(20) NOT NULL CONSTRAINT DF_Matches_Status DEFAULT 'SCHEDULED',
        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_Matches_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_Matches_Round FOREIGN KEY(RoundId) REFERENCES dbo.CompetitionRounds(RoundId),
        CONSTRAINT UQ_Matches_RoundNumber UNIQUE(RoundId,MatchNumber),
        CONSTRAINT CK_Matches_Status CHECK(MatchStatus IN ('SCHEDULED','LIVE','FINISHED','CANCELLED')),
        CONSTRAINT CK_Matches_Number CHECK(MatchNumber>0)
    );
    CREATE TABLE dbo.CompetitionMatchTeams(
        MatchId BIGINT NOT NULL, TeamId INT NOT NULL,
        CONSTRAINT PK_CompetitionMatchTeams PRIMARY KEY(MatchId,TeamId),
        CONSTRAINT FK_MatchTeams_Match FOREIGN KEY(MatchId) REFERENCES dbo.CompetitionMatches(MatchId),
        CONSTRAINT FK_MatchTeams_Team FOREIGN KEY(TeamId) REFERENCES dbo.Teams(TeamId)
    );
END;
IF OBJECT_ID('dbo.ScoreEntries','U') IS NULL
BEGIN
    CREATE TABLE dbo.ScoreEntries(
        ScoreEntryId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ScoreEntries PRIMARY KEY,
        EventId INT NOT NULL, CategoryId INT NOT NULL, TeamId INT NOT NULL,
        RoundId INT NULL, MatchId BIGINT NULL, PointsDelta INT NOT NULL,
        Reason NVARCHAR(500) NOT NULL, IdempotencyKey UNIQUEIDENTIFIER NOT NULL,
        CreatedByUserId INT NOT NULL,
        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_ScoreEntries_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_ScoreEntries_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_ScoreEntries_Category FOREIGN KEY(CategoryId) REFERENCES dbo.Categories(CategoryId),
        CONSTRAINT FK_ScoreEntries_Team FOREIGN KEY(TeamId) REFERENCES dbo.Teams(TeamId),
        CONSTRAINT FK_ScoreEntries_Round FOREIGN KEY(RoundId) REFERENCES dbo.CompetitionRounds(RoundId),
        CONSTRAINT FK_ScoreEntries_Match FOREIGN KEY(MatchId) REFERENCES dbo.CompetitionMatches(MatchId),
        CONSTRAINT FK_ScoreEntries_User FOREIGN KEY(CreatedByUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT UQ_ScoreEntries_Idempotency UNIQUE(IdempotencyKey),
        CONSTRAINT CK_ScoreEntries_Reason CHECK(LEN(LTRIM(RTRIM(Reason)))>0)
    );
    CREATE INDEX IX_ScoreEntries_Leaderboard ON dbo.ScoreEntries(EventId,CategoryId,TeamId,ScoreEntryId) INCLUDE(PointsDelta);
    CREATE INDEX IX_ScoreEntries_Recent ON dbo.ScoreEntries(EventId,ScoreEntryId DESC) INCLUDE(CategoryId,TeamId,PointsDelta,CreatedAt);
END;
GO
