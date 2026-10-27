USE UTA_SUMO_ROBOTICS_CUP;
GO

IF OBJECT_ID('dbo.EventManagementAudit','U') IS NULL
BEGIN
    CREATE TABLE dbo.EventManagementAudit(
      AuditId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_EventManagementAudit_34 PRIMARY KEY,
      EventId INT NOT NULL,
      ActorUserId INT NULL,
      ActionCode VARCHAR(20) NOT NULL,
      PreviousDataJson NVARCHAR(MAX) NULL,
      NewDataJson NVARCHAR(MAX) NOT NULL,
      ChangedAt DATETIME2(3) NOT NULL CONSTRAINT DF_EventManagementAudit_Changed_34 DEFAULT SYSUTCDATETIME(),
      CONSTRAINT FK_EventManagementAudit_Event_34 FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
      CONSTRAINT FK_EventManagementAudit_User_34 FOREIGN KEY(ActorUserId) REFERENCES dbo.Users(UserId),
      CONSTRAINT CK_EventManagementAudit_Action_34 CHECK(ActionCode IN ('CREATED','UPDATED')),
      CONSTRAINT CK_EventManagementAudit_NewJson_34 CHECK(ISJSON(NewDataJson)=1),
      CONSTRAINT CK_EventManagementAudit_OldJson_34 CHECK(PreviousDataJson IS NULL OR ISJSON(PreviousDataJson)=1)
    );
    CREATE INDEX IX_EventManagementAudit_Event_34 ON dbo.EventManagementAudit(EventId,ChangedAt DESC,AuditId DESC);
END;
GO
