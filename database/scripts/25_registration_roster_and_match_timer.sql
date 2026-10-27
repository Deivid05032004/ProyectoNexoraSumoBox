USE UTA_SUMO_ROBOTICS_CUP;
GO

/* New registrations in the official category require exactly two participants
   and one coach. Existing registrations are not rewritten. */
UPDATE ec SET MinParticipants=2,MaxParticipants=2,MinCoaches=1,MaxCoaches=1,
  UpdatedAt=SYSUTCDATETIME()
FROM dbo.EventCategories ec
JOIN dbo.Events e ON e.EventId=ec.EventId
JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId
WHERE e.Name=N'UTA SUMO ROBOTICS CUP 2026' AND e.EditionYear=2026
  AND c.Name=N'MINI SUMO AMATEUR RC';
GO

/* Timer state belongs to each match so a process restart or a second display
   cannot reset/alter the official clock. */
IF COL_LENGTH('dbo.CompetitionMatches','TimerEnabled') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD TimerEnabled BIT NOT NULL
      CONSTRAINT DF_CompetitionMatches_TimerEnabled DEFAULT 0 WITH VALUES;
IF COL_LENGTH('dbo.CompetitionMatches','TimerDurationSeconds') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD TimerDurationSeconds INT NOT NULL
      CONSTRAINT DF_CompetitionMatches_TimerDuration DEFAULT 180 WITH VALUES;
IF COL_LENGTH('dbo.CompetitionMatches','TimerRemainingSeconds') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD TimerRemainingSeconds INT NOT NULL
      CONSTRAINT DF_CompetitionMatches_TimerRemaining DEFAULT 180 WITH VALUES;
IF COL_LENGTH('dbo.CompetitionMatches','TimerStatus') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD TimerStatus VARCHAR(12) NOT NULL
      CONSTRAINT DF_CompetitionMatches_TimerStatus DEFAULT 'STOPPED' WITH VALUES;
IF COL_LENGTH('dbo.CompetitionMatches','TimerStartedAt') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD TimerStartedAt DATETIME2(3) NULL;
IF COL_LENGTH('dbo.CompetitionMatches','TimerUpdatedAt') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD TimerUpdatedAt DATETIME2(3) NOT NULL
      CONSTRAINT DF_CompetitionMatches_TimerUpdated DEFAULT SYSUTCDATETIME() WITH VALUES;
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
               WHERE name='CK_CompetitionMatches_TimerDuration'
                 AND parent_object_id=OBJECT_ID('dbo.CompetitionMatches'))
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_TimerDuration
      CHECK(TimerDurationSeconds BETWEEN 1 AND 5999);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
               WHERE name='CK_CompetitionMatches_TimerRemaining'
                 AND parent_object_id=OBJECT_ID('dbo.CompetitionMatches'))
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_TimerRemaining
      CHECK(TimerRemainingSeconds BETWEEN 0 AND TimerDurationSeconds);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
               WHERE name='CK_CompetitionMatches_TimerStatus'
                 AND parent_object_id=OBJECT_ID('dbo.CompetitionMatches'))
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_TimerStatus
      CHECK(TimerStatus IN ('STOPPED','RUNNING','PAUSED','FINISHED'));
GO

IF EXISTS (SELECT 1 FROM sys.check_constraints
           WHERE name='CK_ActiveCombatHistory_Action'
             AND parent_object_id=OBJECT_ID('dbo.ActiveCombatHistory'))
    ALTER TABLE dbo.ActiveCombatHistory DROP CONSTRAINT CK_ActiveCombatHistory_Action;
ALTER TABLE dbo.ActiveCombatHistory ADD CONSTRAINT CK_ActiveCombatHistory_Action
    CHECK(ActionCode IN ('SELECTED','REPLACED','STATUS_CHANGED','SCORE_CHANGED','DETAILS_CHANGED','TIMER_CHANGED'));
GO
