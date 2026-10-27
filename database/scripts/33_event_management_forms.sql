USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Add event metadata without rewriting or deleting registrations. */
IF COL_LENGTH('dbo.Events','Description') IS NULL
    ALTER TABLE dbo.Events ADD Description NVARCHAR(2000) NULL;
IF COL_LENGTH('dbo.Events','Venue') IS NULL
    ALTER TABLE dbo.Events ADD Venue NVARCHAR(250) NULL;
IF COL_LENGTH('dbo.Events','StartsAt') IS NULL
    ALTER TABLE dbo.Events ADD StartsAt DATETIME2(0) NULL;
IF COL_LENGTH('dbo.Events','EndsAt') IS NULL
    ALTER TABLE dbo.Events ADD EndsAt DATETIME2(0) NULL;
GO

IF OBJECT_ID('dbo.EventFormVersions','U') IS NULL
BEGIN
    CREATE TABLE dbo.EventFormVersions(
      FormVersionId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_EventFormVersions PRIMARY KEY,
      EventId INT NOT NULL,
      VersionNumber INT NOT NULL,
      Title NVARCHAR(200) NOT NULL,
      Description NVARCHAR(2000) NULL,
      FieldsJson NVARCHAR(MAX) NOT NULL,
      IsCurrent BIT NOT NULL CONSTRAINT DF_EventFormVersions_Current DEFAULT 1,
      CreatedByUserId INT NULL,
      CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_EventFormVersions_Created DEFAULT SYSUTCDATETIME(),
      CONSTRAINT FK_EventFormVersions_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
      CONSTRAINT FK_EventFormVersions_User FOREIGN KEY(CreatedByUserId) REFERENCES dbo.Users(UserId),
      CONSTRAINT UQ_EventFormVersions_Number UNIQUE(EventId,VersionNumber),
      CONSTRAINT CK_EventFormVersions_Json CHECK(ISJSON(FieldsJson)=1),
      CONSTRAINT CK_EventFormVersions_Title CHECK(LEN(LTRIM(RTRIM(Title))) BETWEEN 1 AND 200)
    );
    CREATE UNIQUE INDEX UX_EventFormVersions_Current ON dbo.EventFormVersions(EventId) WHERE IsCurrent=1;
END;
GO

IF OBJECT_ID('dbo.RegistrationFormResponses','U') IS NULL
BEGIN
    CREATE TABLE dbo.RegistrationFormResponses(
      RegistrationId INT NOT NULL CONSTRAINT PK_RegistrationFormResponses PRIMARY KEY,
      FormVersionId BIGINT NOT NULL,
      AnswersCiphertext NVARCHAR(MAX) NOT NULL,
      CreatedAt DATETIME2(3) NOT NULL CONSTRAINT DF_RegistrationFormResponses_Created DEFAULT SYSUTCDATETIME(),
      CONSTRAINT FK_RegistrationFormResponses_Registration FOREIGN KEY(RegistrationId) REFERENCES dbo.Registrations(RegistrationId),
      CONSTRAINT FK_RegistrationFormResponses_Form FOREIGN KEY(FormVersionId) REFERENCES dbo.EventFormVersions(FormVersionId)
    );
END;
GO

IF OBJECT_ID('dbo.EventStatusHistory','U') IS NULL
BEGIN
    CREATE TABLE dbo.EventStatusHistory(
      EventStatusHistoryId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_EventsStatusHistory_33 PRIMARY KEY,
      EventId INT NOT NULL,
      PreviousStatus VARCHAR(20) NULL,
      NewStatus VARCHAR(20) NOT NULL,
      Reason NVARCHAR(500) NULL,
      ActorUserId INT NULL,
      ChangedAt DATETIME2(3) NOT NULL CONSTRAINT DF_EventsStatusHistory_Changed_33 DEFAULT SYSUTCDATETIME(),
      CONSTRAINT FK_EventsStatusHistory_Event_33 FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
      CONSTRAINT FK_EventsStatusHistory_User_33 FOREIGN KEY(ActorUserId) REFERENCES dbo.Users(UserId),
      CONSTRAINT CK_EventsStatusHistory_Status_33 CHECK(NewStatus IN ('DRAFT','SCHEDULED','LIVE','PAUSED','FINISHED','CANCELLED'))
    );
    CREATE INDEX IX_EventsStatusHistory_Event_33 ON dbo.EventStatusHistory(EventId,ChangedAt DESC);
END;
GO
