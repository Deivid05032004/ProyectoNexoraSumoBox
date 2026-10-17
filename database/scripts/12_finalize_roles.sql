USE UTA_SUMO_ROBOTICS_CUP;
GO
DECLARE @admin INT=(SELECT RoleId FROM dbo.Roles WHERE Code='ADMIN');
DECLARE @event_manager INT=(SELECT RoleId FROM dbo.Roles WHERE Code='EVENT_MANAGER');
IF @admin IS NULL OR @event_manager IS NULL
    THROW 51020, 'Aplique primero las migraciones del esquema de competencias.', 1;

-- Keep historical audit rows while mapping obsolete role references to the
-- corresponding current role before removing legacy role records.
UPDATE a SET PreviousRoleId=CASE legacy.Code WHEN 'REVIEWER' THEN @event_manager
                                                  WHEN 'TREASURY' THEN @admin END
FROM dbo.UserSecurityAudit a JOIN dbo.Roles legacy ON legacy.RoleId=a.PreviousRoleId
WHERE legacy.Code IN ('REVIEWER','TREASURY');
UPDATE a SET NewRoleId=CASE legacy.Code WHEN 'REVIEWER' THEN @event_manager
                                             WHEN 'TREASURY' THEN @admin END
FROM dbo.UserSecurityAudit a JOIN dbo.Roles legacy ON legacy.RoleId=a.NewRoleId
WHERE legacy.Code IN ('REVIEWER','TREASURY');

IF EXISTS (SELECT 1 FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId
           WHERE r.Code NOT IN ('ADMIN','EVENT_MANAGER','PARTICIPANT'))
    THROW 51021, 'Hay usuarios con roles personalizados; reasígnelos antes de finalizar roles.', 1;
DELETE FROM dbo.Roles WHERE Code IN ('REVIEWER','TREASURY');
GO
