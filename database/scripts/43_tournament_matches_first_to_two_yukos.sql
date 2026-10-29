/* Every official tournament match is first to two Yukos. Manual matches keep
   their existing 1–5 point target. Re-running this script is safe. */
UPDATE dbo.CompetitionMatches
SET ScoreToWin = 2
WHERE StageCode <> 'MANUAL'
  AND ScoreToWin <> 2;

IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID('dbo.CompetitionMatches')
      AND name = 'CK_CompetitionMatches_ScoreToWin'
)
    ALTER TABLE dbo.CompetitionMatches
      DROP CONSTRAINT CK_CompetitionMatches_ScoreToWin;

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID('dbo.CompetitionMatches')
      AND name = 'CK_CompetitionMatches_ScoreToWin'
)
    ALTER TABLE dbo.CompetitionMatches
      ADD CONSTRAINT CK_CompetitionMatches_ScoreToWin
      CHECK ((StageCode = 'MANUAL' AND ScoreToWin BETWEEN 1 AND 5)
          OR (StageCode <> 'MANUAL' AND ScoreToWin = 2));
