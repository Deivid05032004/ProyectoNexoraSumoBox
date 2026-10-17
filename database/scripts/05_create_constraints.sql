USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Reglas de validación del dominio de inscripción y pagos. */
ALTER TABLE dbo.Events
    ADD CONSTRAINT CK_Events_RegistrationDates
    CHECK (RegistrationEnd IS NULL OR RegistrationStart IS NULL
           OR RegistrationEnd >= RegistrationStart);
GO

ALTER TABLE dbo.Registrations
    ADD CONSTRAINT UQ_Registrations_Event_Team_Robot_Category
    UNIQUE (EventId, TeamId, RobotId, CategoryId);
GO

ALTER TABLE dbo.Tariffs
    ADD CONSTRAINT UQ_Tariffs_Event_Category_ValidFrom
    UNIQUE (EventId, CategoryId, ValidFrom);
GO

ALTER TABLE dbo.Payments
    ADD CONSTRAINT CK_Payments_Verification
    CHECK (
        (PaymentStatus = 'PAID' AND VerifiedAt IS NOT NULL)
        OR PaymentStatus <> 'PAID'
    );
GO

ALTER TABLE dbo.Users
    ADD CONSTRAINT CK_Users_TokenVersion CHECK (TokenVersion >= 0),
        CONSTRAINT CK_Users_BcryptHash CHECK (
            PasswordHash LIKE '$2a$%' OR PasswordHash LIKE '$2b$%' OR PasswordHash LIKE '$2y$%'
        );
GO

ALTER TABLE dbo.UserSecurityAudit
    ADD CONSTRAINT CK_UserSecurityAudit_Action
    CHECK (ActionCode IN ('ACCOUNT_CREATED','ACCOUNT_UPDATED','PASSWORD_CHANGED'));
GO

ALTER TABLE dbo.Payments
    ADD CONSTRAINT CK_Payments_VerificationMetadata
    CHECK (
        (PaymentStatus IN ('PAID','REJECTED') AND VerifiedByUserId IS NOT NULL AND VerifiedAt IS NOT NULL)
        OR (PaymentStatus IN ('PENDING','IN_REVIEW') AND VerifiedByUserId IS NULL AND VerifiedAt IS NULL)
    );
GO
