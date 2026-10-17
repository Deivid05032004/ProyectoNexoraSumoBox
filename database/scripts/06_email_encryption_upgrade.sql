/* Online-compatible data-preserving migration for email identity and encrypted PII.
   The runner backfills ciphertext/HMAC in the same transaction after these DDL batches. */
USE UTA_SUMO_ROBOTICS_CUP;
GO
IF COL_LENGTH('dbo.Users','EmailCiphertext') IS NULL
    ALTER TABLE dbo.Users ADD EmailCiphertext NVARCHAR(512) NULL;
IF COL_LENGTH('dbo.Users','EmailLookupHash') IS NULL
    ALTER TABLE dbo.Users ADD EmailLookupHash CHAR(64) NULL;
IF COL_LENGTH('dbo.PaymentReceipts','EncryptionVersion') IS NULL
    ALTER TABLE dbo.PaymentReceipts ADD EncryptionVersion TINYINT NOT NULL
        CONSTRAINT DF_PaymentReceipts_EncryptionVersion DEFAULT(0) WITH VALUES;
GO
IF COL_LENGTH('dbo.Users','Username') IS NOT NULL
    ALTER TABLE dbo.Users ALTER COLUMN Username NVARCHAR(512) NOT NULL;
ALTER TABLE dbo.Users ALTER COLUMN FirstName NVARCHAR(512) NOT NULL;
ALTER TABLE dbo.Users ALTER COLUMN LastName NVARCHAR(512) NOT NULL;
ALTER TABLE dbo.Participants ALTER COLUMN FirstName NVARCHAR(512) NOT NULL;
ALTER TABLE dbo.Participants ALTER COLUMN LastName NVARCHAR(512) NOT NULL;
ALTER TABLE dbo.Participants ALTER COLUMN MobilePhone NVARCHAR(128) NULL;
ALTER TABLE dbo.Teams ALTER COLUMN Name NVARCHAR(512) NOT NULL;
ALTER TABLE dbo.Teams ALTER COLUMN ContactPhone NVARCHAR(128) NULL;
ALTER TABLE dbo.Robots ALTER COLUMN Name NVARCHAR(512) NOT NULL;
ALTER TABLE dbo.Robots ALTER COLUMN RobotDescription NVARCHAR(1024) NULL;
ALTER TABLE dbo.Registrations ALTER COLUMN Notes NVARCHAR(2048) NULL;
ALTER TABLE dbo.Payments ALTER COLUMN PaymentReference NVARCHAR(512) NULL;
ALTER TABLE dbo.StatusHistory ALTER COLUMN Comments NVARCHAR(2048) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name='CK_Users_BcryptHash')
    ALTER TABLE dbo.Users DROP CONSTRAINT CK_Users_BcryptHash;
GO
