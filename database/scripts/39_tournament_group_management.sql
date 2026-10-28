USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Dynamic tournament groups are separate from the legacy A-D schedule tables.
   This keeps existing matches and live scoreboard data intact. */
IF OBJECT_ID('dbo.TournamentGroups','U') IS NULL
BEGIN
    CREATE TABLE dbo.TournamentGroups(
        TournamentGroupId INT IDENTITY(1,1) NOT NULL,
        EventId INT NOT NULL,
        CategoryId INT NOT NULL,
        GroupName NVARCHAR(100) NOT NULL,
        GroupCode NVARCHAR(20) NOT NULL,
        MaxTeams SMALLINT NOT NULL,
        CreatedByUserId INT NOT NULL,
        UpdatedByUserId INT NOT NULL,
        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_TournamentGroups_CreatedAt DEFAULT SYSUTCDATETIME(),
        UpdatedAt DATETIME2 NOT NULL CONSTRAINT DF_TournamentGroups_UpdatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_TournamentGroups PRIMARY KEY(TournamentGroupId),
        CONSTRAINT FK_TournamentGroups_EventCategory FOREIGN KEY(EventId,CategoryId)
            REFERENCES dbo.EventCategories(EventId,CategoryId),
        CONSTRAINT FK_TournamentGroups_CreatedBy FOREIGN KEY(CreatedByUserId)
            REFERENCES dbo.Users(UserId),
        CONSTRAINT FK_TournamentGroups_UpdatedBy FOREIGN KEY(UpdatedByUserId)
            REFERENCES dbo.Users(UserId),
        CONSTRAINT CK_TournamentGroups_Name CHECK(LEN(LTRIM(RTRIM(GroupName))) BETWEEN 1 AND 100),
        CONSTRAINT CK_TournamentGroups_Code CHECK(LEN(LTRIM(RTRIM(GroupCode))) BETWEEN 1 AND 20),
        CONSTRAINT CK_TournamentGroups_MaxTeams CHECK(MaxTeams BETWEEN 1 AND 64),
        CONSTRAINT UQ_TournamentGroups_EventCategoryCode UNIQUE(EventId,CategoryId,GroupCode),
        CONSTRAINT UQ_TournamentGroups_EventCategoryName UNIQUE(EventId,CategoryId,GroupName)
    );
END;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.TournamentGroups')
               AND name='IX_TournamentGroups_EventCategory')
    CREATE INDEX IX_TournamentGroups_EventCategory
        ON dbo.TournamentGroups(EventId,CategoryId,GroupName)
        INCLUDE(GroupCode,MaxTeams,UpdatedAt);
GO

IF OBJECT_ID('dbo.TournamentGroupRegistrations','U') IS NULL
BEGIN
    CREATE TABLE dbo.TournamentGroupRegistrations(
        TournamentGroupId INT NOT NULL,
        RegistrationId INT NOT NULL,
        AssignedByUserId INT NOT NULL,
        AssignedAt DATETIME2 NOT NULL CONSTRAINT DF_TournamentGroupRegistrations_AssignedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_TournamentGroupRegistrations PRIMARY KEY(TournamentGroupId,RegistrationId),
        CONSTRAINT UQ_TournamentGroupRegistrations_Registration UNIQUE(RegistrationId),
        CONSTRAINT FK_TournamentGroupRegistrations_Group FOREIGN KEY(TournamentGroupId)
            REFERENCES dbo.TournamentGroups(TournamentGroupId) ON DELETE CASCADE,
        CONSTRAINT FK_TournamentGroupRegistrations_Registration FOREIGN KEY(RegistrationId)
            REFERENCES dbo.Registrations(RegistrationId),
        CONSTRAINT FK_TournamentGroupRegistrations_User FOREIGN KEY(AssignedByUserId)
            REFERENCES dbo.Users(UserId)
    );
END;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.TournamentGroupRegistrations')
               AND name='IX_TournamentGroupRegistrations_Group')
    CREATE INDEX IX_TournamentGroupRegistrations_Group
        ON dbo.TournamentGroupRegistrations(TournamentGroupId,AssignedAt,RegistrationId);
GO
