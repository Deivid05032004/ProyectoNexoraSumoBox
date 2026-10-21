/* A matchup now pins the actual robot selected for each team. Nullable during
   transition so previously created matches remain readable and can be upgraded. */
IF COL_LENGTH('dbo.CompetitionMatchTeams','RobotId') IS NULL
    ALTER TABLE dbo.CompetitionMatchTeams ADD RobotId INT NULL;
GO
IF COL_LENGTH('dbo.CompetitionMatchTeams','TeamPosition') IS NULL
    ALTER TABLE dbo.CompetitionMatchTeams ADD TeamPosition TINYINT NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_MatchTeams_TeamPosition')
    ALTER TABLE dbo.CompetitionMatchTeams ADD CONSTRAINT CK_MatchTeams_TeamPosition
        CHECK(TeamPosition IS NULL OR TeamPosition BETWEEN 1 AND 8);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.CompetitionMatchTeams') AND name='UX_MatchTeams_Position')
    CREATE UNIQUE INDEX UX_MatchTeams_Position ON dbo.CompetitionMatchTeams(MatchId,TeamPosition)
        WHERE TeamPosition IS NOT NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_MatchTeams_Robot')
    ALTER TABLE dbo.CompetitionMatchTeams ADD CONSTRAINT FK_MatchTeams_Robot
        FOREIGN KEY(RobotId) REFERENCES dbo.Robots(RobotId);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.CompetitionMatchTeams') AND name='IX_MatchTeams_Robot')
    CREATE INDEX IX_MatchTeams_Robot ON dbo.CompetitionMatchTeams(RobotId) WHERE RobotId IS NOT NULL;
GO
