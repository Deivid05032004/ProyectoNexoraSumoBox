USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Per-match direction for the official clock. Existing clocks keep the
   countdown behavior and start with zero elapsed time. */
IF COL_LENGTH('dbo.CompetitionMatches','TimerDirection') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD TimerDirection VARCHAR(4) NOT NULL
      CONSTRAINT DF_CompetitionMatches_TimerDirection DEFAULT 'DOWN' WITH VALUES;
IF COL_LENGTH('dbo.CompetitionMatches','TimerElapsedSeconds') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD TimerElapsedSeconds INT NOT NULL
      CONSTRAINT DF_CompetitionMatches_TimerElapsed DEFAULT 0 WITH VALUES;
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
               WHERE name='CK_CompetitionMatches_TimerDirection'
                 AND parent_object_id=OBJECT_ID('dbo.CompetitionMatches'))
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_TimerDirection
      CHECK(TimerDirection IN ('UP','DOWN'));
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
               WHERE name='CK_CompetitionMatches_TimerElapsed'
                 AND parent_object_id=OBJECT_ID('dbo.CompetitionMatches'))
    ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT CK_CompetitionMatches_TimerElapsed
      CHECK(TimerElapsedSeconds BETWEEN 0 AND TimerDurationSeconds);
GO
