USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Stable provider subject mapping. Store Google's `sub`, never an OAuth token. */
IF OBJECT_ID('dbo.UserExternalIdentities', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.UserExternalIdentities (
        ExternalIdentityId BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_UserExternalIdentities PRIMARY KEY,
        UserId INT NOT NULL,
        ProviderCode VARCHAR(30) NOT NULL,
        ProviderSubject NVARCHAR(255) NOT NULL,
        LinkedAt DATETIME2 NOT NULL CONSTRAINT DF_UserExternalIdentities_LinkedAt
            DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_UserExternalIdentities_User FOREIGN KEY (UserId)
            REFERENCES dbo.Users(UserId),
        CONSTRAINT CK_UserExternalIdentities_Provider
            CHECK (ProviderCode IN ('GOOGLE')),
        CONSTRAINT UQ_UserExternalIdentities_User_Provider
            UNIQUE (UserId, ProviderCode),
        CONSTRAINT UQ_UserExternalIdentities_Provider_Subject
            UNIQUE (ProviderCode, ProviderSubject)
    );
END;
GO
