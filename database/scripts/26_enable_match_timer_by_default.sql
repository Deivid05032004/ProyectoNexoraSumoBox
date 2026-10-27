USE UTA_SUMO_ROBOTICS_CUP;
GO

/* The public scoreboard should show the official clock by default. Staff may
   still disable it through the protected timer configuration endpoint. */
IF EXISTS (SELECT 1 FROM sys.default_constraints
           WHERE name='DF_CompetitionMatches_TimerEnabled'
             AND parent_object_id=OBJECT_ID('dbo.CompetitionMatches'))
    ALTER TABLE dbo.CompetitionMatches DROP CONSTRAINT DF_CompetitionMatches_TimerEnabled;
ALTER TABLE dbo.CompetitionMatches ADD CONSTRAINT DF_CompetitionMatches_TimerEnabled
    DEFAULT 1 FOR TimerEnabled;
GO

/* Turn on the clock for the currently selected match without starting it or
   resetting the value configured by an operator. */
UPDATE m SET TimerEnabled=1,TimerUpdatedAt=SYSUTCDATETIME()
FROM dbo.CompetitionMatches m
JOIN dbo.ActiveCombat ac ON ac.MatchId=m.MatchId AND ac.ActiveCombatId=1
WHERE m.TimerEnabled=0;
GO
