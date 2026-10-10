
USE UTA_SUMO_ROBOTICS_CUP;
GO

-- Categoría inicial
IF NOT EXISTS (
    SELECT 1 FROM dbo.Categories
    WHERE Name = N'MINI SUMO RC AMATEUR'
)
BEGIN
    INSERT INTO dbo.Categories (Name, Description)
    VALUES (
        N'MINI SUMO RC AMATEUR',
        N'Categoría de robots mini sumo controlados remotamente.'
    );
END;
GO

-- Estados de inscripción
IF NOT EXISTS (SELECT 1 FROM dbo.RegistrationStatuses WHERE Code = 'PENDING')
    INSERT INTO dbo.RegistrationStatuses (Code, Name)
    VALUES ('PENDING', N'Pendiente');

IF NOT EXISTS (SELECT 1 FROM dbo.RegistrationStatuses WHERE Code = 'PAYMENT_PENDING')
    INSERT INTO dbo.RegistrationStatuses (Code, Name)
    VALUES ('PAYMENT_PENDING', N'Pago pendiente');

IF NOT EXISTS (SELECT 1 FROM dbo.RegistrationStatuses WHERE Code = 'PAYMENT_REVIEW')
    INSERT INTO dbo.RegistrationStatuses (Code, Name)
    VALUES ('PAYMENT_REVIEW', N'Pago en verificación');

IF NOT EXISTS (SELECT 1 FROM dbo.RegistrationStatuses WHERE Code = 'APPROVED')
    INSERT INTO dbo.RegistrationStatuses (Code, Name)
    VALUES ('APPROVED', N'Aprobada');

IF NOT EXISTS (SELECT 1 FROM dbo.RegistrationStatuses WHERE Code = 'OBSERVED')
    INSERT INTO dbo.RegistrationStatuses (Code, Name)
    VALUES ('OBSERVED', N'Observada');

IF NOT EXISTS (SELECT 1 FROM dbo.RegistrationStatuses WHERE Code = 'REJECTED')
    INSERT INTO dbo.RegistrationStatuses (Code, Name)
    VALUES ('REJECTED', N'Rechazada');

IF NOT EXISTS (SELECT 1 FROM dbo.RegistrationStatuses WHERE Code = 'CANCELLED')
    INSERT INTO dbo.RegistrationStatuses (Code, Name)
    VALUES ('CANCELLED', N'Cancelada');
GO

-- Roles administrativos
IF NOT EXISTS (SELECT 1 FROM dbo.Roles WHERE Code = 'ADMIN')
    INSERT INTO dbo.Roles (Code, Name)
    VALUES ('ADMIN', N'Administrador');

IF NOT EXISTS (SELECT 1 FROM dbo.Roles WHERE Code = 'REVIEWER')
    INSERT INTO dbo.Roles (Code, Name)
    VALUES ('REVIEWER', N'Revisor');

IF NOT EXISTS (SELECT 1 FROM dbo.Roles WHERE Code = 'TREASURY')
    INSERT INTO dbo.Roles (Code, Name)
    VALUES ('TREASURY', N'Tesorería');
GO

-- Verificación
SELECT Code, Name
FROM dbo.RegistrationStatuses
ORDER BY StatusId;

SELECT Code, Name
FROM dbo.Roles
ORDER BY RoleId;

SELECT CategoryId, Name
FROM dbo.Categories;
GO
