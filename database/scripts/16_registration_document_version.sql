/* Keep an explicit encryption format version for generated private PDFs. */
IF COL_LENGTH('dbo.RegistrationDocuments','EncryptionVersion') IS NULL
    ALTER TABLE dbo.RegistrationDocuments ADD EncryptionVersion TINYINT NOT NULL
        CONSTRAINT DF_RegistrationDocuments_EncryptionVersion DEFAULT(1) WITH VALUES;
GO
