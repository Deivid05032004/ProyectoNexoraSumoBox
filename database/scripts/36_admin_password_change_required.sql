/* Force first-access password replacement for the fixed local ADMIN identity. */
IF COL_LENGTH('dbo.Users', 'MustChangePassword') IS NULL
BEGIN
    ALTER TABLE dbo.Users
    ADD MustChangePassword BIT NOT NULL
        CONSTRAINT DF_Users_MustChangePassword DEFAULT (0) WITH VALUES;
END;
GO
