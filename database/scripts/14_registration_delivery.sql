/* Per-event registration presentation/payment config and durable receipt/email metadata.
   Additive migration: existing registrations and payment evidence remain untouched. */
IF COL_LENGTH('dbo.Payments','CurrencyCode') IS NULL
BEGIN
    ALTER TABLE dbo.Payments ADD CurrencyCode CHAR(3) NOT NULL
        CONSTRAINT DF_Payments_CurrencyCode DEFAULT 'USD' WITH VALUES;
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_Payments_CurrencyCode')
    ALTER TABLE dbo.Payments ADD CONSTRAINT CK_Payments_CurrencyCode CHECK(CurrencyCode LIKE '[A-Z][A-Z][A-Z]');
GO

IF OBJECT_ID('dbo.EventRegistrationConfigs','U') IS NULL
BEGIN
    CREATE TABLE dbo.EventRegistrationConfigs (
        EventId INT NOT NULL CONSTRAINT PK_EventRegistrationConfigs PRIMARY KEY,
        OrganizationName NVARCHAR(200) NOT NULL CONSTRAINT DF_EventRegistrationConfigs_Organization DEFAULT N'UTA SUMO ROBOTICS CUP',
        FormTitle NVARCHAR(200) NOT NULL CONSTRAINT DF_EventRegistrationConfigs_Title DEFAULT N'Inscripción al evento',
        FormDescription NVARCHAR(2000) NULL,
        FormInstructions NVARCHAR(4000) NULL,
        PaymentInstructions NVARCHAR(MAX) NULL,
        PaymentMethodsJson NVARCHAR(4000) NULL,
        ContactEmail NVARCHAR(254) NULL,
        ContactPhone NVARCHAR(50) NULL,
        ReceiptMessage NVARCHAR(2000) NULL,
        Currency CHAR(3) NOT NULL CONSTRAINT DF_EventRegistrationConfigs_Currency DEFAULT 'USD',
        IsEnabled BIT NOT NULL CONSTRAINT DF_EventRegistrationConfigs_Enabled DEFAULT 1,
        UpdatedByUserId INT NULL,
        UpdatedAt DATETIME2 NOT NULL CONSTRAINT DF_EventRegistrationConfigs_UpdatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_EventRegistrationConfigs_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_EventRegistrationConfigs_User FOREIGN KEY(UpdatedByUserId) REFERENCES dbo.Users(UserId),
        CONSTRAINT CK_EventRegistrationConfigs_Currency CHECK (Currency LIKE '[A-Z][A-Z][A-Z]')
    );
END;
GO

IF OBJECT_ID('dbo.RegistrationDocuments','U') IS NULL
BEGIN
    CREATE TABLE dbo.RegistrationDocuments (
        DocumentId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_RegistrationDocuments PRIMARY KEY,
        RegistrationId INT NOT NULL,
        DocumentType VARCHAR(30) NOT NULL,
        StorageKey NVARCHAR(100) NOT NULL CONSTRAINT UQ_RegistrationDocuments_StorageKey UNIQUE,
        MediaType VARCHAR(100) NOT NULL,
        Sha256 CHAR(64) NOT NULL,
        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_RegistrationDocuments_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_RegistrationDocuments_Registration FOREIGN KEY(RegistrationId) REFERENCES dbo.Registrations(RegistrationId),
        CONSTRAINT CK_RegistrationDocuments_Type CHECK(DocumentType IN ('PAYMENT_INSTRUCTION'))
    );
    CREATE INDEX IX_RegistrationDocuments_Registration ON dbo.RegistrationDocuments(RegistrationId,CreatedAt DESC);
END;
GO

IF OBJECT_ID('dbo.EmailOutbox','U') IS NULL
BEGIN
    CREATE TABLE dbo.EmailOutbox (
        OutboxId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_EmailOutbox PRIMARY KEY,
        RegistrationId INT NOT NULL,
        DocumentId BIGINT NULL,
        MessageType VARCHAR(40) NOT NULL,
        RecipientCiphertext NVARCHAR(512) NOT NULL,
        Subject NVARCHAR(1024) NOT NULL,
        BodyText NVARCHAR(MAX) NOT NULL,
        DeliveryStatus VARCHAR(20) NOT NULL CONSTRAINT DF_EmailOutbox_Status DEFAULT 'PENDING',
        Attempts SMALLINT NOT NULL CONSTRAINT DF_EmailOutbox_Attempts DEFAULT 0,
        LastError NVARCHAR(500) NULL,
        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_EmailOutbox_CreatedAt DEFAULT SYSUTCDATETIME(),
        SentAt DATETIME2 NULL,
        CONSTRAINT FK_EmailOutbox_Registration FOREIGN KEY(RegistrationId) REFERENCES dbo.Registrations(RegistrationId),
        CONSTRAINT FK_EmailOutbox_Document FOREIGN KEY(DocumentId) REFERENCES dbo.RegistrationDocuments(DocumentId),
        CONSTRAINT CK_EmailOutbox_Status CHECK(DeliveryStatus IN ('PENDING','SENT','FAILED')),
        CONSTRAINT UQ_EmailOutbox_Registration_Type UNIQUE(RegistrationId,MessageType)
    );
    CREATE INDEX IX_EmailOutbox_Status_Created ON dbo.EmailOutbox(DeliveryStatus,CreatedAt);
END;
GO

IF OBJECT_ID('dbo.EventRegistrationConfigAudit','U') IS NULL
BEGIN
    CREATE TABLE dbo.EventRegistrationConfigAudit (
        AuditId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_EventRegistrationConfigAudit PRIMARY KEY,
        EventId INT NOT NULL,
        ActorUserId INT NOT NULL,
        PreviousConfigCiphertext NVARCHAR(MAX) NULL,
        NewConfigCiphertext NVARCHAR(MAX) NOT NULL,
        ChangedAt DATETIME2 NOT NULL CONSTRAINT DF_EventRegistrationConfigAudit_ChangedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_EventRegistrationConfigAudit_Event FOREIGN KEY(EventId) REFERENCES dbo.Events(EventId),
        CONSTRAINT FK_EventRegistrationConfigAudit_Actor FOREIGN KEY(ActorUserId) REFERENCES dbo.Users(UserId)
    );
    CREATE INDEX IX_EventRegistrationConfigAudit_Event ON dbo.EventRegistrationConfigAudit(EventId,ChangedAt DESC);
END;
GO
