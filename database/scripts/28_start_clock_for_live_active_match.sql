USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Bring the already-running active match under server-controlled timing when
   deploying the automatic-start behavior. No score or match state is changed. */
UPDATE m SET TimerStatus='RUNNING',TimerStartedAt=SYSUTCDATETIME(),
  TimerUpdatedAt=SYSUTCDATETIME()
FROM dbo.ActiveCombat ac
JOIN dbo.CompetitionMatches m ON m.MatchId=ac.MatchId
JOIN dbo.CompetitionRounds cr ON cr.RoundId=m.RoundId
JOIN dbo.Events e ON e.EventId=cr.EventId
WHERE ac.ActiveCombatId=1 AND m.MatchStatus='LIVE' AND e.CompetitionStatus='LIVE'
  AND m.TimerEnabled=1 AND m.TimerStatus IN ('STOPPED','PAUSED')
  AND ((m.TimerDirection='DOWN' AND m.TimerRemainingSeconds>0)
       OR (m.TimerDirection='UP' AND m.TimerElapsedSeconds<m.TimerDurationSeconds));
GO
