USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Tournament operations are stored beside the existing append-only score,
   round and match records. ActiveCombat remains the legacy primary display
   pointer; LiveDohyoMatches supports up to four concurrent public boards. */
IF COL_LENGTH('dbo.CompetitionMatches','StageCode') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD StageCode VARCHAR(20) NOT NULL
      CONSTRAINT DF_CompetitionMatches_StageCode DEFAULT 'MANUAL' WITH VALUES;
IF COL_LENGTH('dbo.CompetitionMatches','GroupCode') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD GroupCode CHAR(1) NULL;
IF COL_LENGTH('dbo.CompetitionMatches','DohyoNumber') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD DohyoNumber TINYINT NULL;
IF COL_LENGTH('dbo.CompetitionMatches','ScoreToWin') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD ScoreToWin TINYINT NOT NULL
      CONSTRAINT DF_CompetitionMatches_ScoreToWin DEFAULT 2 WITH VALUES;
IF COL_LENGTH('dbo.CompetitionMatches','BracketSlot') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD BracketSlot VARCHAR(12) NULL;
IF COL_LENGTH('dbo.CompetitionMatches','WinnerTeamId') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD WinnerTeamId INT NULL;
IF COL_LENGTH('dbo.CompetitionMatches','LoserTeamId') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD LoserTeamId INT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_CompetitionMatches_StageCode')
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_StageCode
      CHECK(StageCode IN ('MANUAL','GROUP','QUARTERFINAL','SEMIFINAL','THIRD_PLACE','FINAL'));
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_CompetitionMatches_GroupCode')
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_GroupCode
      CHECK(GroupCode IS NULL OR GroupCode IN ('A','B','C','D'));
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_CompetitionMatches_Dohyo')
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_Dohyo
      CHECK(DohyoNumber IS NULL OR DohyoNumber BETWEEN 1 AND 4);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_CompetitionMatches_ScoreToWin')
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_ScoreToWin
      CHECK(ScoreToWin BETWEEN 1 AND 5);
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_CompetitionMatches_WinnerTeam')
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT FK_CompetitionMatches_WinnerTeam
      FOREIGN KEY(WinnerTeamId) REFERENCES dbo.Teams(TeamId);
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_CompetitionMatches_LoserTeam')
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT FK_CompetitionMatches_LoserTeam
      FOREIGN KEY(LoserTeamId) REFERENCES dbo.Teams(TeamId);
GO

IF OBJECT_ID('dbo.TournamentTeamGroups','U') IS NULL
BEGIN
    CREATE TABLE dbo.TournamentTeamGroups(
        EventId INT NOT NULL, CategoryId INT NOT NULL, TeamId INT NOT NULL,
        RobotId INT NOT NULL, GroupCode CHAR(1) NOT NULL,
        AssignedByUserId INT NOT NULL,
        AssignedAt DATETIME2 NOT NULL CONSTRAINT DF_TournamentTeamGroups_AssignedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_TournamentTeamGroups PRIMARY KEY(EventId,CategoryId,TeamId),
        CONSTRAINT UQ_TournamentTeamGroups_Robot UNIQUE(EventId,CategoryId,RobotId),
        CONSTRAINT FK_TournamentTeamGroups_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_TournamentTeamGroups_Category FOREIGN KEY(CategoryId) REFERENCES dbo.Categories(CategoryId),
        CONSTRAINT FK_TournamentTeamGroups_Team FOREIGN KEY(TeamId) REFERENCES dbo.Teams(TeamId),
        CONSTRAINT FK_TournamentTeamGroups_Robot FOREIGN KEY(RobotId) REFERENCES dbo.Robots(RobotId),
        CONSTRAINT FK_TournamentTeamGroups_User FOREIGN KEY(AssignedByUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT CK_TournamentTeamGroups_Group CHECK(GroupCode IN ('A','B','C','D'))
    );
    CREATE INDEX IX_TournamentTeamGroups_Group ON dbo.TournamentTeamGroups(EventId,CategoryId,GroupCode,TeamId);
END;
GO

IF OBJECT_ID('dbo.TournamentPhaseState','U') IS NULL
BEGIN
    CREATE TABLE dbo.TournamentPhaseState(
        EventId INT NOT NULL, CategoryId INT NOT NULL,
        CurrentPhase VARCHAR(20) NOT NULL CONSTRAINT DF_TournamentPhaseState_Phase DEFAULT 'GROUP',
        CreatedByUserId INT NOT NULL, UpdatedByUserId INT NOT NULL,
        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_TournamentPhaseState_CreatedAt DEFAULT SYSUTCDATETIME(),
        UpdatedAt DATETIME2 NOT NULL CONSTRAINT DF_TournamentPhaseState_UpdatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_TournamentPhaseState PRIMARY KEY(EventId,CategoryId),
        CONSTRAINT FK_TournamentPhaseState_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_TournamentPhaseState_Category FOREIGN KEY(CategoryId) REFERENCES dbo.Categories(CategoryId),
        CONSTRAINT FK_TournamentPhaseState_CreatedBy FOREIGN KEY(CreatedByUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT FK_TournamentPhaseState_UpdatedBy FOREIGN KEY(UpdatedByUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT CK_TournamentPhaseState_Phase CHECK(CurrentPhase IN ('GROUP','QUARTERFINAL','SEMIFINAL','THIRD_PLACE','FINAL','FINISHED'))
    );
END;
GO

IF OBJECT_ID('dbo.LiveDohyoMatches','U') IS NULL
BEGIN
    CREATE TABLE dbo.LiveDohyoMatches(
        EventId INT NOT NULL, CategoryId INT NOT NULL, DohyoNumber TINYINT NOT NULL,
        MatchId BIGINT NOT NULL, UpdatedByUserId INT NOT NULL,
        UpdatedAt DATETIME2 NOT NULL CONSTRAINT DF_LiveDohyoMatches_UpdatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_LiveDohyoMatches PRIMARY KEY(EventId,CategoryId,DohyoNumber),
        CONSTRAINT UQ_LiveDohyoMatches_Match UNIQUE(EventId,CategoryId,MatchId),
        CONSTRAINT FK_LiveDohyoMatches_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_LiveDohyoMatches_Category FOREIGN KEY(CategoryId) REFERENCES dbo.Categories(CategoryId),
        CONSTRAINT FK_LiveDohyoMatches_Match FOREIGN KEY(MatchId) REFERENCES dbo.CompetitionMatches(MatchId),
        CONSTRAINT FK_LiveDohyoMatches_User FOREIGN KEY(UpdatedByUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT CK_LiveDohyoMatches_Dohyo CHECK(DohyoNumber BETWEEN 1 AND 4)
    );
    CREATE INDEX IX_LiveDohyoMatches_Match ON dbo.LiveDohyoMatches(MatchId);
END;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.CompetitionMatches') AND name='IX_CompetitionMatches_TournamentQueue')
    CREATE INDEX IX_CompetitionMatches_TournamentQueue
      ON dbo.CompetitionMatches(RoundId,StageCode,GroupCode,MatchStatus,MatchNumber)
      INCLUDE(DohyoNumber,ScoreToWin,WinnerTeamId,LoserTeamId,BracketSlot);
GO
