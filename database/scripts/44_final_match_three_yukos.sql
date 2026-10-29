/* Official bracket bouts are first-to-two Yukos; the grand final is first-to-three. */
IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID('dbo.CompetitionMatches')
      AND name = 'CK_CompetitionMatches_ScoreToWin'
)
    ALTER TABLE dbo.CompetitionMatches
      DROP CONSTRAINT CK_CompetitionMatches_ScoreToWin;

UPDATE dbo.CompetitionMatches
SET ScoreToWin = CASE WHEN StageCode = 'FINAL' THEN 3 ELSE 2 END
WHERE StageCode <> 'MANUAL'
  AND ScoreToWin <> CASE WHEN StageCode = 'FINAL' THEN 3 ELSE 2 END;

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID('dbo.CompetitionMatches')
      AND name = 'CK_CompetitionMatches_ScoreToWin'
)
    ALTER TABLE dbo.CompetitionMatches
      ADD CONSTRAINT CK_CompetitionMatches_ScoreToWin
      CHECK ((StageCode = 'MANUAL' AND ScoreToWin BETWEEN 1 AND 5)
          OR (StageCode = 'FINAL' AND ScoreToWin = 3)
          OR (StageCode <> 'MANUAL' AND StageCode <> 'FINAL' AND ScoreToWin = 2));
