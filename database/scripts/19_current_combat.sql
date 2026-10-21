/* Single selected combat for public scoreboard clients. History and score
   movements make administrative changes traceable; no existing match is changed. */
IF OBJECT_ID('dbo.ActiveCombat','U') IS NULL
BEGIN
    CREATE TABLE dbo.ActiveCombat (
        ActiveCombatId TINYINT NOT NULL CONSTRAINT PK_ActiveCombat PRIMARY KEY,
        MatchId BIGINT NOT NULL,
        UpdatedByUserId INT NOT NULL,
        UpdatedAt DATETIME2 NOT NULL CONSTRAINT DF_ActiveCombat_UpdatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT CK_ActiveCombat_Singleton CHECK(ActiveCombatId=1),
        CONSTRAINT UQ_ActiveCombat_Match UNIQUE(MatchId),
        CONSTRAINT FK_ActiveCombat_Match FOREIGN KEY(MatchId) REFERENCES dbo.CompetitionMatches(MatchId),
        CONSTRAINT FK_ActiveCombat_User FOREIGN KEY(UpdatedByUserId) REFERENCES dbo.Users(UserId)
    );
END;
GO

IF OBJECT_ID('dbo.ActiveCombatHistory','U') IS NULL
BEGIN
    CREATE TABLE dbo.ActiveCombatHistory (
        HistoryId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ActiveCombatHistory PRIMARY KEY,
        PreviousMatchId BIGINT NULL,
        NewMatchId BIGINT NOT NULL,
        ActorUserId INT NOT NULL,
        ActionCode VARCHAR(20) NOT NULL,
        Reason NVARCHAR(500) NULL,
        ChangedAt DATETIME2 NOT NULL CONSTRAINT DF_ActiveCombatHistory_ChangedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_ActiveCombatHistory_PreviousMatch FOREIGN KEY(PreviousMatchId) REFERENCES dbo.CompetitionMatches(MatchId),
        CONSTRAINT FK_ActiveCombatHistory_NewMatch FOREIGN KEY(NewMatchId) REFERENCES dbo.CompetitionMatches(MatchId),
        CONSTRAINT FK_ActiveCombatHistory_Actor FOREIGN KEY(ActorUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT CK_ActiveCombatHistory_Action CHECK(ActionCode IN ('SELECTED','REPLACED','STATUS_CHANGED','SCORE_CHANGED')),
        CONSTRAINT CK_ActiveCombatHistory_Reason CHECK(Reason IS NULL OR LEN(LTRIM(RTRIM(Reason)))>0)
    );
    CREATE INDEX IX_ActiveCombatHistory_ChangedAt ON dbo.ActiveCombatHistory(ChangedAt DESC,HistoryId DESC);
END;
GO
