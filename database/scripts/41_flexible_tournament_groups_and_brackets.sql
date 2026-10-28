USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Allow event managers to create any practical number of named groups and
   store automatic bracket byes without changing registrations or old matches. */
IF EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.CompetitionMatches')
           AND name='IX_CompetitionMatches_TournamentQueue')
    DROP INDEX IX_CompetitionMatches_TournamentQueue ON dbo.CompetitionMatches;
IF EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.CompetitionMatches')
           AND name='IX_CompetitionMatches_TournamentGroup')
    DROP INDEX IX_CompetitionMatches_TournamentGroup ON dbo.CompetitionMatches;
IF EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.TournamentTeamGroups')
           AND name='IX_TournamentTeamGroups_Group')
    DROP INDEX IX_TournamentTeamGroups_Group ON dbo.TournamentTeamGroups;
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_CompetitionMatches_GroupCode')
    ALTER TABLE dbo.CompetitionMatches DROP CONSTRAINT CK_CompetitionMatches_GroupCode;
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_TournamentTeamGroups_Group')
    ALTER TABLE dbo.TournamentTeamGroups DROP CONSTRAINT CK_TournamentTeamGroups_Group;
GO

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.CompetitionMatches')
           AND name='GroupCode' AND (TYPE_NAME(system_type_id)<>'nvarchar' OR max_length<40))
    ALTER TABLE dbo.CompetitionMatches ALTER COLUMN GroupCode NVARCHAR(20) NULL;
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.TournamentTeamGroups')
           AND name='GroupCode' AND (TYPE_NAME(system_type_id)<>'nvarchar' OR max_length<40))
    ALTER TABLE dbo.TournamentTeamGroups ALTER COLUMN GroupCode NVARCHAR(20) NOT NULL;
GO

ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_GroupCode
  CHECK(GroupCode IS NULL OR LEN(LTRIM(RTRIM(GroupCode))) BETWEEN 1 AND 20);
ALTER TABLE dbo.TournamentTeamGroups ADD CONSTRAINT CK_TournamentTeamGroups_Group
  CHECK(LEN(LTRIM(RTRIM(GroupCode))) BETWEEN 1 AND 20);
CREATE INDEX IX_TournamentTeamGroups_Group
  ON dbo.TournamentTeamGroups(EventId,CategoryId,GroupCode,TeamId);
CREATE INDEX IX_CompetitionMatches_TournamentQueue
  ON dbo.CompetitionMatches(RoundId,StageCode,GroupCode,MatchStatus,MatchNumber)
  INCLUDE(DohyoNumber,ScoreToWin,WinnerTeamId,LoserTeamId,BracketSlot,TournamentGroupId);
CREATE INDEX IX_CompetitionMatches_TournamentGroup
  ON dbo.CompetitionMatches(TournamentGroupId,MatchStatus,MatchNumber)
  INCLUDE(StageCode,GroupCode,RoundId,DohyoNumber,ScoreToWin);
GO

IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_CompetitionMatches_StageCode')
    ALTER TABLE dbo.CompetitionMatches DROP CONSTRAINT CK_CompetitionMatches_StageCode;
ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_StageCode CHECK
  (StageCode IN ('MANUAL','GROUP','ROUND_OF_64','ROUND_OF_32','ROUND_OF_16',
                 'QUARTERFINAL','SEMIFINAL','THIRD_PLACE','FINAL'));
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_TournamentPhaseState_Phase')
    ALTER TABLE dbo.TournamentPhaseState DROP CONSTRAINT CK_TournamentPhaseState_Phase;
ALTER TABLE dbo.TournamentPhaseState ADD CONSTRAINT CK_TournamentPhaseState_Phase CHECK
  (CurrentPhase IN ('GROUP','ROUND_OF_64','ROUND_OF_32','ROUND_OF_16',
                    'QUARTERFINAL','SEMIFINAL','THIRD_PLACE','FINAL','FINISHED'));
GO

IF OBJECT_ID('dbo.TournamentBracketByes','U') IS NULL
BEGIN
    CREATE TABLE dbo.TournamentBracketByes(
        EventId INT NOT NULL,
        CategoryId INT NOT NULL,
        StageCode VARCHAR(20) NOT NULL,
        TeamId INT NOT NULL,
        RobotId INT NOT NULL,
        SeedNumber INT NOT NULL,
        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_TournamentBracketByes_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_TournamentBracketByes PRIMARY KEY(EventId,CategoryId,StageCode,TeamId),
        CONSTRAINT UQ_TournamentBracketByes_Seed UNIQUE(EventId,CategoryId,StageCode,SeedNumber),
        CONSTRAINT FK_TournamentBracketByes_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_TournamentBracketByes_Category FOREIGN KEY(CategoryId) REFERENCES dbo.Categories(CategoryId),
        CONSTRAINT FK_TournamentBracketByes_Team FOREIGN KEY(TeamId) REFERENCES dbo.Teams(TeamId),
        CONSTRAINT FK_TournamentBracketByes_Robot FOREIGN KEY(RobotId) REFERENCES dbo.Robots(RobotId),
        CONSTRAINT CK_TournamentBracketByes_Seed CHECK(SeedNumber>0),
        CONSTRAINT CK_TournamentBracketByes_Stage CHECK
          (StageCode IN ('ROUND_OF_64','ROUND_OF_32','ROUND_OF_16','QUARTERFINAL','SEMIFINAL'))
    );
    CREATE INDEX IX_TournamentBracketByes_Stage
      ON dbo.TournamentBracketByes(EventId,CategoryId,StageCode,SeedNumber)
      INCLUDE(TeamId,RobotId);
END;
GO
