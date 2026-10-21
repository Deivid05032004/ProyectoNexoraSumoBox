/* Search encrypted payment references without storing the value in plaintext. */
IF COL_LENGTH('dbo.Payments','PaymentReferenceLookupHash') IS NULL
    ALTER TABLE dbo.Payments ADD PaymentReferenceLookupHash CHAR(64) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Payments') AND name='IX_Payments_PaymentReferenceLookupHash')
    CREATE INDEX IX_Payments_PaymentReferenceLookupHash ON dbo.Payments(PaymentReferenceLookupHash)
        WHERE PaymentReferenceLookupHash IS NOT NULL;
GO
