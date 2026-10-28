USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Preserve the configured group relation on each group-stage match. This is
   additive and safe to apply repeatedly; existing matches remain unchanged. */
IF COL_LENGTH('dbo.CompetitionMatches','TournamentGroupId') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD TournamentGroupId INT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_CompetitionMatches_TournamentGroup')
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT FK_CompetitionMatches_TournamentGroup
      FOREIGN KEY(TournamentGroupId) REFERENCES dbo.TournamentGroups(TournamentGroupId);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.CompetitionMatches')
               AND name='IX_CompetitionMatches_TournamentGroup')
    CREATE INDEX IX_CompetitionMatches_TournamentGroup
      ON dbo.CompetitionMatches(TournamentGroupId,MatchStatus,MatchNumber)
      INCLUDE(StageCode,GroupCode,RoundId,DohyoNumber,ScoreToWin);
GO
