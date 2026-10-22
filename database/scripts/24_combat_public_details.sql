USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Human-readable notes displayed with the active match. Existing matches retain
   an empty note; names and institutional identities remain sourced from SQL. */
IF COL_LENGTH('dbo.CompetitionMatches','PublicDetails') IS NULL
    ALTER TABLE dbo.CompetitionMatches ADD PublicDetails NVARCHAR(1000) NULL;
GO

IF EXISTS (SELECT 1 FROM sys.check_constraints
           WHERE name='CK_ActiveCombatHistory_Action'
             AND parent_object_id=OBJECT_ID('dbo.ActiveCombatHistory'))
    ALTER TABLE dbo.ActiveCombatHistory DROP CONSTRAINT CK_ActiveCombatHistory_Action;
ALTER TABLE dbo.ActiveCombatHistory ADD CONSTRAINT CK_ActiveCombatHistory_Action
    CHECK(ActionCode IN ('SELECTED','REPLACED','STATUS_CHANGED','SCORE_CHANGED','DETAILS_CHANGED'));
GO
