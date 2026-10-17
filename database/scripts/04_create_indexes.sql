USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Índices para búsquedas y relaciones consultadas con frecuencia. */
CREATE INDEX IX_Teams_InstitutionId
    ON dbo.Teams (InstitutionId);
GO
CREATE INDEX IX_Teams_OwnerUserId ON dbo.Teams (OwnerUserId);
GO
CREATE INDEX IX_Participants_InstitutionId
    ON dbo.Participants (InstitutionId);
GO
CREATE UNIQUE INDEX UX_Participants_UserId ON dbo.Participants(UserId) WHERE UserId IS NOT NULL;
GO
CREATE INDEX IX_Robots_OwnerUserId ON dbo.Robots(OwnerUserId);
GO
CREATE INDEX IX_Registrations_Event_Category
    ON dbo.Registrations (EventId, CategoryId);
GO
CREATE INDEX IX_Registrations_TeamId
    ON dbo.Registrations (TeamId);
GO
CREATE INDEX IX_Registrations_StatusId
    ON dbo.Registrations (StatusId);
GO
CREATE INDEX IX_RegistrationParticipants_ParticipantId
    ON dbo.RegistrationParticipants (ParticipantId);
GO
CREATE INDEX IX_Tariffs_Event_Category_Active
    ON dbo.Tariffs (EventId, CategoryId, IsActive);
GO
CREATE UNIQUE INDEX UX_Payments_RegistrationId ON dbo.Payments(RegistrationId);
GO
CREATE UNIQUE INDEX UX_PaymentReceipts_OneCurrent ON dbo.PaymentReceipts(PaymentId) WHERE IsCurrent=1;
GO
CREATE INDEX IX_Payments_Status_CreatedAt
    ON dbo.Payments (PaymentStatus, CreatedAt);
GO
CREATE INDEX IX_StatusHistory_Registration_ChangedAt
    ON dbo.StatusHistory (RegistrationId, ChangedAt DESC);
GO
CREATE INDEX IX_UserSecurityAudit_Target_CreatedAt ON dbo.UserSecurityAudit(TargetUserId, CreatedAt DESC, AuditId DESC);
GO
