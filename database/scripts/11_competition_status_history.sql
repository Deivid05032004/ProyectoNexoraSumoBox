USE UTA_SUMO_ROBOTICS_CUP;
GO
IF OBJECT_ID('dbo.CompetitionEventStatusHistory','U') IS NULL
BEGIN
    CREATE TABLE dbo.CompetitionEventStatusHistory(
        HistoryId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CompetitionEventStatusHistory PRIMARY KEY,
        EventId INT NOT NULL,
        PreviousStatus VARCHAR(20) NOT NULL,
        NewStatus VARCHAR(20) NOT NULL,
        ChangedByUserId INT NOT NULL,
        Reason NVARCHAR(500) NULL,
        ChangedAt DATETIME2 NOT NULL CONSTRAINT DF_EventStatusHistory_ChangedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_EventStatusHistory_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_EventStatusHistory_User FOREIGN KEY(ChangedByUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT CK_EventStatusHistory_Reason CHECK(Reason IS NULL OR LEN(LTRIM(RTRIM(Reason)))>0)
    );
    CREATE INDEX IX_EventStatusHistory_Event ON dbo.CompetitionEventStatusHistory(EventId,HistoryId DESC);
END;
GO
