USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Relaciones entre entidades. */
ALTER TABLE dbo.Teams
    ADD CONSTRAINT FK_Teams_Institutions
    FOREIGN KEY (InstitutionId) REFERENCES dbo.Institutions(InstitutionId);
GO

ALTER TABLE dbo.Participants
    ADD CONSTRAINT FK_Participants_Institutions
    FOREIGN KEY (InstitutionId) REFERENCES dbo.Institutions(InstitutionId);
GO

ALTER TABLE dbo.Participants ADD CONSTRAINT FK_Participants_Users
    FOREIGN KEY (UserId) REFERENCES dbo.Users(UserId);
GO
ALTER TABLE dbo.Teams ADD CONSTRAINT FK_Teams_OwnerUser
    FOREIGN KEY (OwnerUserId) REFERENCES dbo.Users(UserId);
GO
ALTER TABLE dbo.Robots ADD CONSTRAINT FK_Robots_OwnerUser
    FOREIGN KEY (OwnerUserId) REFERENCES dbo.Users(UserId);
GO

ALTER TABLE dbo.Registrations
    ADD CONSTRAINT FK_Registrations_Events
        FOREIGN KEY (EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_Registrations_Categories
        FOREIGN KEY (CategoryId) REFERENCES dbo.Categories(CategoryId),
        CONSTRAINT FK_Registrations_Teams
        FOREIGN KEY (TeamId) REFERENCES dbo.Teams(TeamId),
        CONSTRAINT FK_Registrations_Robots
        FOREIGN KEY (RobotId) REFERENCES dbo.Robots(RobotId),
        CONSTRAINT FK_Registrations_Statuses
        FOREIGN KEY (StatusId) REFERENCES dbo.RegistrationStatuses(StatusId);
GO

ALTER TABLE dbo.Registrations ADD CONSTRAINT FK_Registrations_CreatorUser
    FOREIGN KEY (CreatedByUserId) REFERENCES dbo.Users(UserId);
GO

ALTER TABLE dbo.RegistrationParticipants
    ADD CONSTRAINT FK_RegParticipants_Registrations
        FOREIGN KEY (RegistrationId) REFERENCES dbo.Registrations(RegistrationId),
        CONSTRAINT FK_RegParticipants_Participants
        FOREIGN KEY (ParticipantId) REFERENCES dbo.Participants(ParticipantId);
GO

ALTER TABLE dbo.Tariffs
    ADD CONSTRAINT FK_Tariffs_Events
        FOREIGN KEY (EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_Tariffs_Categories
        FOREIGN KEY (CategoryId) REFERENCES dbo.Categories(CategoryId);
GO

ALTER TABLE dbo.Payments
    ADD CONSTRAINT FK_Payments_Registrations
        FOREIGN KEY (RegistrationId) REFERENCES dbo.Registrations(RegistrationId),
        CONSTRAINT FK_Payments_Tariffs
        FOREIGN KEY (TariffId) REFERENCES dbo.Tariffs(TariffId),
        CONSTRAINT FK_Payments_VerifiedByUser
        FOREIGN KEY (VerifiedByUserId) REFERENCES dbo.Users(UserId);
GO

ALTER TABLE dbo.PaymentReceipts
    ADD CONSTRAINT FK_PaymentReceipts_Payments
        FOREIGN KEY (PaymentId) REFERENCES dbo.Payments(PaymentId),
        CONSTRAINT FK_PaymentReceipts_Users
        FOREIGN KEY (UploadedByUserId) REFERENCES dbo.Users(UserId);
GO

ALTER TABLE dbo.UserSecurityAudit
    ADD CONSTRAINT FK_UserSecurityAudit_Target FOREIGN KEY (TargetUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT FK_UserSecurityAudit_Actor FOREIGN KEY (ActorUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT FK_UserSecurityAudit_PreviousRole FOREIGN KEY (PreviousRoleId) REFERENCES dbo.Roles(RoleId),
        CONSTRAINT FK_UserSecurityAudit_NewRole FOREIGN KEY (NewRoleId) REFERENCES dbo.Roles(RoleId);
GO

ALTER TABLE dbo.Users
    ADD CONSTRAINT FK_Users_Roles
    FOREIGN KEY (RoleId) REFERENCES dbo.Roles(RoleId);
GO

ALTER TABLE dbo.StatusHistory
    ADD CONSTRAINT FK_StatusHistory_Registrations
        FOREIGN KEY (RegistrationId) REFERENCES dbo.Registrations(RegistrationId),
        CONSTRAINT FK_StatusHistory_PreviousStatus
        FOREIGN KEY (PreviousStatusId) REFERENCES dbo.RegistrationStatuses(StatusId),
        CONSTRAINT FK_StatusHistory_NewStatus
        FOREIGN KEY (NewStatusId) REFERENCES dbo.RegistrationStatuses(StatusId),
        CONSTRAINT FK_StatusHistory_Users
        FOREIGN KEY (ChangedByUserId) REFERENCES dbo.Users(UserId);
GO
