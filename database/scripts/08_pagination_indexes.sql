USE UTA_SUMO_ROBOTICS_CUP;
GO
/* Indexes aligned with server-side page filters and stable ordering. */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Registrations') AND name='IX_Registrations_Owner_RegisteredAt')
    CREATE INDEX IX_Registrations_Owner_RegisteredAt
      ON dbo.Registrations(CreatedByUserId,RegisteredAt DESC,RegistrationId DESC)
      INCLUDE(EventId,CategoryId,TeamId,RobotId,StatusId);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Registrations') AND name='IX_Registrations_Event_RegisteredAt')
    CREATE INDEX IX_Registrations_Event_RegisteredAt
      ON dbo.Registrations(EventId,RegisteredAt DESC,RegistrationId DESC)
      INCLUDE(CategoryId,TeamId,RobotId,StatusId);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Payments') AND name='IX_Payments_Registration_CreatedAt')
    CREATE INDEX IX_Payments_Registration_CreatedAt
      ON dbo.Payments(RegistrationId,CreatedAt DESC,PaymentId DESC)
      INCLUDE(TariffId,Amount,PaymentStatus,VerifiedAt);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.StatusHistory') AND name='IX_StatusHistory_Registration_ChangedAt_History')
    CREATE INDEX IX_StatusHistory_Registration_ChangedAt_History
      ON dbo.StatusHistory(RegistrationId,ChangedAt,HistoryId)
      INCLUDE(PreviousStatusId,NewStatusId,ChangedByUserId);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Teams') AND name='IX_Teams_Owner_Team')
    CREATE INDEX IX_Teams_Owner_Team
      ON dbo.Teams(OwnerUserId,TeamId DESC) INCLUDE(InstitutionId);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Robots') AND name='IX_Robots_Owner_Robot')
    CREATE INDEX IX_Robots_Owner_Robot
      ON dbo.Robots(OwnerUserId,RobotId DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Events') AND name='IX_Events_Active_Edition')
    CREATE INDEX IX_Events_Active_Edition
      ON dbo.Events(IsActive,EditionYear DESC,Name,EventId)
      INCLUDE(RegistrationStart,RegistrationEnd);
GO
