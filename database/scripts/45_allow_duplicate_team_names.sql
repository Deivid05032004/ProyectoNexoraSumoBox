/* Team names are labels, not global identifiers. Different teams may use the
   same name; TeamId remains the identity used by registrations and robots. */
IF EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('dbo.Teams')
      AND name = 'UX_Teams_NameLookupHash'
)
    DROP INDEX UX_Teams_NameLookupHash ON dbo.Teams;
