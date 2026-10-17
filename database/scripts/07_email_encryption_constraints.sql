/* Finalize the email-only identity and checks after the transactional backfill. */
USE UTA_SUMO_ROBOTICS_CUP;
GO
IF EXISTS (SELECT 1 FROM dbo.Users WHERE EmailCiphertext IS NULL OR EmailLookupHash IS NULL)
    THROW 51200, 'El backfill de correo cifrado no quedó completo; no se aplicarán las restricciones.', 1;
IF EXISTS (SELECT 1 FROM dbo.Users GROUP BY EmailLookupHash HAVING COUNT_BIG(*)>1)
    THROW 51201, 'Hay correos duplicados en usuarios existentes; resuélvalos antes de continuar.', 1;
GO
ALTER TABLE dbo.Users ALTER COLUMN EmailCiphertext NVARCHAR(512) NOT NULL;
ALTER TABLE dbo.Users ALTER COLUMN EmailLookupHash CHAR(64) NOT NULL;
GO
DECLARE @usernameUq sysname;
SELECT TOP (1) @usernameUq=kc.name
FROM sys.key_constraints kc
JOIN sys.index_columns ic ON ic.object_id=kc.parent_object_id AND ic.index_id=kc.unique_index_id
JOIN sys.columns col ON col.object_id=ic.object_id AND col.column_id=ic.column_id
WHERE kc.parent_object_id=OBJECT_ID('dbo.Users') AND kc.type='UQ' AND col.name='Username';
IF @usernameUq IS NOT NULL
BEGIN
    DECLARE @dropUsernameUq NVARCHAR(300) = N'ALTER TABLE dbo.Users DROP CONSTRAINT ' + QUOTENAME(@usernameUq);
    EXEC sys.sp_executesql @dropUsernameUq;
END
IF COL_LENGTH('dbo.Users','Username') IS NOT NULL
    ALTER TABLE dbo.Users DROP COLUMN Username;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Users') AND name='UX_Users_EmailLookupHash')
    CREATE UNIQUE INDEX UX_Users_EmailLookupHash ON dbo.Users(EmailLookupHash);
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_Users_PasswordHash')
    ALTER TABLE dbo.Users WITH CHECK ADD CONSTRAINT CK_Users_PasswordHash
    CHECK (PasswordHash LIKE '$argon2id$%' OR PasswordHash LIKE '$2a$%' OR PasswordHash LIKE '$2b$%' OR PasswordHash LIKE '$2y$%');
GO
