/* Versioned public event/category regulations. Files are encrypted in private
   storage; the database owns metadata, lifecycle and immutable file hashes. */
IF OBJECT_ID('dbo.EventRegulations','U') IS NULL
BEGIN
    CREATE TABLE dbo.EventRegulations (
        RegulationId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_EventRegulations PRIMARY KEY,
        EventId INT NOT NULL,
        CategoryId INT NULL,
        Title NVARCHAR(200) NOT NULL,
        VersionNumber INT NOT NULL,
        OriginalFilename NVARCHAR(255) NOT NULL,
        StorageKey NVARCHAR(100) NOT NULL,
        MediaType VARCHAR(100) NOT NULL CONSTRAINT DF_EventRegulations_MediaType DEFAULT 'application/pdf',
        FileSizeBytes BIGINT NOT NULL,
        Sha256 CHAR(64) NOT NULL,
        StatusCode VARCHAR(20) NOT NULL CONSTRAINT DF_EventRegulations_Status DEFAULT 'DRAFT',
        EffectiveFrom DATE NOT NULL CONSTRAINT DF_EventRegulations_EffectiveFrom DEFAULT (CONVERT(date,GETDATE())),
        EffectiveUntil DATE NULL,
        UploadedByUserId INT NULL,
        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_EventRegulations_CreatedAt DEFAULT SYSUTCDATETIME(),
        PublishedAt DATETIME2 NULL,
        CONSTRAINT FK_EventRegulations_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_EventRegulations_Category FOREIGN KEY(CategoryId) REFERENCES dbo.Categories(CategoryId),
        CONSTRAINT FK_EventRegulations_Uploader FOREIGN KEY(UploadedByUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT UQ_EventRegulations_StorageKey UNIQUE(StorageKey),
        CONSTRAINT UQ_EventRegulations_ScopeVersion UNIQUE(EventId,CategoryId,VersionNumber),
        CONSTRAINT CK_EventRegulations_Title CHECK(LEN(LTRIM(RTRIM(Title))) BETWEEN 1 AND 200),
        CONSTRAINT CK_EventRegulations_Version CHECK(VersionNumber > 0),
        CONSTRAINT CK_EventRegulations_Size CHECK(FileSizeBytes BETWEEN 1 AND 104857600),
        CONSTRAINT CK_EventRegulations_Status CHECK(StatusCode IN ('DRAFT','PUBLISHED','ARCHIVED')),
        CONSTRAINT CK_EventRegulations_Dates CHECK(EffectiveUntil IS NULL OR EffectiveUntil >= EffectiveFrom),
        CONSTRAINT CK_EventRegulations_MediaType CHECK(MediaType='application/pdf')
    );

    CREATE UNIQUE INDEX UX_EventRegulations_OnePublishedPerScope
        ON dbo.EventRegulations(EventId,CategoryId)
        WHERE StatusCode='PUBLISHED';
    CREATE INDEX IX_EventRegulations_PublicLookup
        ON dbo.EventRegulations(EventId,CategoryId,StatusCode,EffectiveFrom DESC,RegulationId DESC)
        INCLUDE(Title,VersionNumber,EffectiveUntil,FileSizeBytes,Sha256,PublishedAt);
    CREATE INDEX IX_EventRegulations_AdminPage
        ON dbo.EventRegulations(EventId,StatusCode,CreatedAt DESC,RegulationId DESC)
        INCLUDE(CategoryId,Title,VersionNumber,EffectiveFrom,EffectiveUntil);
END;
GO

IF OBJECT_ID('dbo.EventRegulationHistory','U') IS NULL
BEGIN
    CREATE TABLE dbo.EventRegulationHistory (
        HistoryId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_EventRegulationHistory PRIMARY KEY,
        RegulationId BIGINT NOT NULL,
        ActorUserId INT NULL,
        ActionCode VARCHAR(20) NOT NULL,
        PreviousStatus VARCHAR(20) NULL,
        NewStatus VARCHAR(20) NOT NULL,
        ChangedAt DATETIME2 NOT NULL CONSTRAINT DF_EventRegulationHistory_ChangedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_EventRegulationHistory_Regulation FOREIGN KEY(RegulationId) REFERENCES dbo.EventRegulations(RegulationId),
        CONSTRAINT FK_EventRegulationHistory_Actor FOREIGN KEY(ActorUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT CK_EventRegulationHistory_Action CHECK(ActionCode IN ('CREATED','UPDATED','PUBLISHED','ARCHIVED')),
        CONSTRAINT CK_EventRegulationHistory_Status CHECK(NewStatus IN ('DRAFT','PUBLISHED','ARCHIVED'))
    );
    CREATE INDEX IX_EventRegulationHistory_Regulation
        ON dbo.EventRegulationHistory(RegulationId,ChangedAt DESC,HistoryId DESC);
END;
GO
