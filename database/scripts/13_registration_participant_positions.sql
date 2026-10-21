USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Preserve the submitted roster order without changing historical roles. */
IF COL_LENGTH('dbo.RegistrationParticipants', 'RegistrationPosition') IS NULL
BEGIN
    ALTER TABLE dbo.RegistrationParticipants
        ADD RegistrationPosition TINYINT NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_RegistrationParticipants_Position'
      AND parent_object_id = OBJECT_ID('dbo.RegistrationParticipants')
)
BEGIN
    ALTER TABLE dbo.RegistrationParticipants
        ADD CONSTRAINT CK_RegistrationParticipants_Position
        CHECK (RegistrationPosition IS NULL OR RegistrationPosition BETWEEN 1 AND 3);
END;
GO

/* Backfill only unambiguous legacy rosters (one participant or two participants
   plus one coach). Other historical rows remain NULL rather than guessing. */
;WITH Roster AS (
    SELECT RegistrationId, ParticipantId, Role,
           COUNT(*) OVER (PARTITION BY RegistrationId) AS MemberCount,
           SUM(CASE WHEN Role = 'PARTICIPANT' THEN 1 ELSE 0 END)
               OVER (PARTITION BY RegistrationId) AS ParticipantCount,
           SUM(CASE WHEN Role = 'COACH' THEN 1 ELSE 0 END)
               OVER (PARTITION BY RegistrationId) AS CoachCount,
           ROW_NUMBER() OVER (
               PARTITION BY RegistrationId
               ORDER BY CASE WHEN Role = 'COACH' THEN 3 ELSE 1 END, ParticipantId
           ) AS RosterPosition
    FROM dbo.RegistrationParticipants
)
UPDATE rp
SET RegistrationPosition = CONVERT(TINYINT, r.RosterPosition)
FROM dbo.RegistrationParticipants rp
JOIN Roster r ON r.RegistrationId = rp.RegistrationId
             AND r.ParticipantId = rp.ParticipantId
WHERE rp.RegistrationPosition IS NULL
  AND r.RosterPosition <= 3
  AND (
      (r.MemberCount = 1 AND r.ParticipantCount = 1 AND r.CoachCount = 0)
      OR (r.MemberCount = 3 AND r.ParticipantCount = 2 AND r.CoachCount = 1)
  );
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'UX_RegistrationParticipants_Position'
      AND object_id = OBJECT_ID('dbo.RegistrationParticipants')
)
BEGIN
    CREATE UNIQUE INDEX UX_RegistrationParticipants_Position
        ON dbo.RegistrationParticipants(RegistrationId, RegistrationPosition)
        WHERE RegistrationPosition IS NOT NULL;
END;
GO
