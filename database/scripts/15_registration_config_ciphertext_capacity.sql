/* Encrypted values need more storage than their plaintext input limits.
   Widen only the config text fields; no value is rewritten or discarded. */
ALTER TABLE dbo.EventRegistrationConfigs ALTER COLUMN FormDescription NVARCHAR(MAX) NULL;
ALTER TABLE dbo.EventRegistrationConfigs ALTER COLUMN FormInstructions NVARCHAR(MAX) NULL;
ALTER TABLE dbo.EventRegistrationConfigs ALTER COLUMN ContactPhone NVARCHAR(MAX) NULL;
ALTER TABLE dbo.EventRegistrationConfigs ALTER COLUMN ReceiptMessage NVARCHAR(MAX) NULL;
GO
