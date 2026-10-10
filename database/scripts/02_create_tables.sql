
USE UTA_SUMO_ROBOTICS_CUP;
GO

-- 1. Instituciones
CREATE TABLE dbo.Institutions (
    InstitutionId INT IDENTITY(1,1) PRIMARY KEY,
    Name NVARCHAR(150) NOT NULL UNIQUE,
    IsActive BIT NOT NULL DEFAULT 1,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
GO

-- 2. Categorías de competición
CREATE TABLE dbo.Categories (
    CategoryId INT IDENTITY(1,1) PRIMARY KEY,
    Name NVARCHAR(100) NOT NULL UNIQUE,
    Description NVARCHAR(500) NULL,
    IsActive BIT NOT NULL DEFAULT 1,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
GO

-- 3. Ediciones del torneo
CREATE TABLE dbo.Events (
    EventId INT IDENTITY(1,1) PRIMARY KEY,
    Name NVARCHAR(150) NOT NULL,
    EditionYear SMALLINT NOT NULL,
    RegistrationStart DATE NULL,
    RegistrationEnd DATE NULL,
    IsActive BIT NOT NULL DEFAULT 1,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    CONSTRAINT UQ_Events_Name_Year UNIQUE (Name, EditionYear)
);
GO

-- 4. Equipos
CREATE TABLE dbo.Teams (
    TeamId INT IDENTITY(1,1) PRIMARY KEY,
    Name NVARCHAR(120) NOT NULL,
    InstitutionId INT NOT NULL,
    ContactPhone NVARCHAR(25) NULL,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    CONSTRAINT FK_Teams_Institutions
        FOREIGN KEY (InstitutionId)
        REFERENCES dbo.Institutions(InstitutionId)
);
GO

-- 5. Personas participantes y entrenadores
CREATE TABLE dbo.Participants (
    ParticipantId INT IDENTITY(1,1) PRIMARY KEY,
    FirstName NVARCHAR(100) NOT NULL,
    LastName NVARCHAR(100) NOT NULL,
    MobilePhone NVARCHAR(25) NULL,
    InstitutionId INT NOT NULL,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    CONSTRAINT FK_Participants_Institutions
        FOREIGN KEY (InstitutionId)
        REFERENCES dbo.Institutions(InstitutionId)
);
GO

-- 6. Robots registrados
CREATE TABLE dbo.Robots (
    RobotId INT IDENTITY(1,1) PRIMARY KEY,
    Name NVARCHAR(120) NOT NULL,
    RobotDescription NVARCHAR(500) NULL,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
GO

-- 7. Estados de inscripción
CREATE TABLE dbo.RegistrationStatuses (
    StatusId INT IDENTITY(1,1) PRIMARY KEY,
    Code VARCHAR(30) NOT NULL UNIQUE,
    Name NVARCHAR(80) NOT NULL UNIQUE
);
GO

-- 8. Inscripciones
CREATE TABLE dbo.Registrations (
    RegistrationId INT IDENTITY(1,1) PRIMARY KEY,
    EventId INT NOT NULL,
    CategoryId INT NOT NULL,
    TeamId INT NOT NULL,
    RobotId INT NOT NULL,
    StatusId INT NOT NULL,
    RegistrationCode UNIQUEIDENTIFIER NOT NULL
        DEFAULT NEWID(),
    RegisteredAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    Notes NVARCHAR(1000) NULL,

    CONSTRAINT FK_Registrations_Events
        FOREIGN KEY (EventId) REFERENCES dbo.Events(EventId),

    CONSTRAINT FK_Registrations_Categories
        FOREIGN KEY (CategoryId) REFERENCES dbo.Categories(CategoryId),

    CONSTRAINT FK_Registrations_Teams
        FOREIGN KEY (TeamId) REFERENCES dbo.Teams(TeamId),

    CONSTRAINT FK_Registrations_Robots
        FOREIGN KEY (RobotId) REFERENCES dbo.Robots(RobotId),

    CONSTRAINT FK_Registrations_Statuses
        FOREIGN KEY (StatusId)
        REFERENCES dbo.RegistrationStatuses(StatusId),

    CONSTRAINT UQ_Registrations_Code UNIQUE (RegistrationCode)
);
GO

-- 9. Participantes vinculados a cada inscripción
CREATE TABLE dbo.RegistrationParticipants (
    RegistrationId INT NOT NULL,
    ParticipantId INT NOT NULL,
    Role VARCHAR(20) NOT NULL,

    CONSTRAINT PK_RegistrationParticipants
        PRIMARY KEY (RegistrationId, ParticipantId),

    CONSTRAINT FK_RegParticipants_Registrations
        FOREIGN KEY (RegistrationId)
        REFERENCES dbo.Registrations(RegistrationId),

    CONSTRAINT FK_RegParticipants_Participants
        FOREIGN KEY (ParticipantId)
        REFERENCES dbo.Participants(ParticipantId),

    CONSTRAINT CK_RegParticipants_Role
        CHECK (Role IN ('PARTICIPANT', 'COACH'))
);
GO

-- 10. Tarifas de inscripción
CREATE TABLE dbo.Tariffs (
    TariffId INT IDENTITY(1,1) PRIMARY KEY,
    EventId INT NOT NULL,
    CategoryId INT NOT NULL,
    Amount DECIMAL(10,2) NOT NULL,
    ValidFrom DATE NOT NULL,
    ValidUntil DATE NULL,
    IsActive BIT NOT NULL DEFAULT 1,

    CONSTRAINT FK_Tariffs_Events
        FOREIGN KEY (EventId) REFERENCES dbo.Events(EventId),

    CONSTRAINT FK_Tariffs_Categories
        FOREIGN KEY (CategoryId) REFERENCES dbo.Categories(CategoryId),

    CONSTRAINT CK_Tariffs_Amount CHECK (Amount >= 0),
    CONSTRAINT CK_Tariffs_Dates
        CHECK (ValidUntil IS NULL OR ValidUntil >= ValidFrom)
);
GO

-- 11. Pagos
CREATE TABLE dbo.Payments (
    PaymentId INT IDENTITY(1,1) PRIMARY KEY,
    RegistrationId INT NOT NULL,
    TariffId INT NOT NULL,
    Amount DECIMAL(10,2) NOT NULL,
    PaymentStatus VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    PaymentReference NVARCHAR(150) NULL,
    VerifiedByUserId INT NULL,
    VerifiedAt DATETIME2 NULL,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),

    CONSTRAINT FK_Payments_Registrations
        FOREIGN KEY (RegistrationId)
        REFERENCES dbo.Registrations(RegistrationId),

    CONSTRAINT FK_Payments_Tariffs
        FOREIGN KEY (TariffId) REFERENCES dbo.Tariffs(TariffId),

    CONSTRAINT CK_Payments_Amount CHECK (Amount >= 0),

    CONSTRAINT CK_Payments_Status
        CHECK (PaymentStatus IN
            ('PENDING', 'IN_REVIEW', 'PAID', 'REJECTED'))
);
GO

-- 12. Roles de usuario
CREATE TABLE dbo.Roles (
    RoleId INT IDENTITY(1,1) PRIMARY KEY,
    Code VARCHAR(30) NOT NULL UNIQUE,
    Name NVARCHAR(80) NOT NULL UNIQUE
);
GO

-- 13. Usuarios administrativos y revisores
CREATE TABLE dbo.Users (
    UserId INT IDENTITY(1,1) PRIMARY KEY,
    Username NVARCHAR(80) NOT NULL UNIQUE,
    PasswordHash NVARCHAR(255) NOT NULL,
    FirstName NVARCHAR(100) NOT NULL,
    LastName NVARCHAR(100) NOT NULL,
    RoleId INT NOT NULL,
    IsActive BIT NOT NULL DEFAULT 1,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),

    CONSTRAINT FK_Users_Roles
        FOREIGN KEY (RoleId) REFERENCES dbo.Roles(RoleId)
);
GO

-- 14. Historial de cambios de estado
CREATE TABLE dbo.StatusHistory (
    HistoryId BIGINT IDENTITY(1,1) PRIMARY KEY,
    RegistrationId INT NOT NULL,
    PreviousStatusId INT NULL,
    NewStatusId INT NOT NULL,
    ChangedByUserId INT NULL,
    Comments NVARCHAR(1000) NULL,
    ChangedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),

    CONSTRAINT FK_StatusHistory_Registrations
        FOREIGN KEY (RegistrationId)
        REFERENCES dbo.Registrations(RegistrationId),

    CONSTRAINT FK_StatusHistory_PreviousStatus
        FOREIGN KEY (PreviousStatusId)
        REFERENCES dbo.RegistrationStatuses(StatusId),

    CONSTRAINT FK_StatusHistory_NewStatus
        FOREIGN KEY (NewStatusId)
        REFERENCES dbo.RegistrationStatuses(StatusId),

    CONSTRAINT FK_StatusHistory_Users
        FOREIGN KEY (ChangedByUserId)
        REFERENCES dbo.Users(UserId)
);
GO
