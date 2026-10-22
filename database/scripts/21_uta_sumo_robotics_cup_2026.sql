-- Official 2026 event and Mini Sumo Amateur RC registration tariff.
-- The regulation PDF is imported separately with scripts/import_event_regulation.py.

IF NOT EXISTS (
    SELECT 1 FROM dbo.Categories WHERE Name=N'MINI SUMO AMATEUR RC'
)
BEGIN
    UPDATE dbo.Categories
    SET Name=N'MINI SUMO AMATEUR RC',
        Description=N'Categoría Mini Sumo Amateur RC conforme al reglamento oficial.'
    WHERE Name=N'MINI SUMO RC AMATEUR'
      AND NOT EXISTS (SELECT 1 FROM dbo.Categories WHERE Name=N'MINI SUMO AMATEUR RC');
END;

IF NOT EXISTS (
    SELECT 1 FROM dbo.Categories WHERE Name=N'MINI SUMO AMATEUR RC'
)
BEGIN
    INSERT INTO dbo.Categories(Name,Description)
    VALUES(N'MINI SUMO AMATEUR RC',N'Categoría Mini Sumo Amateur RC conforme al reglamento oficial.');
END;

DECLARE @CategoryId INT = (
    SELECT TOP (1) CategoryId FROM dbo.Categories
    WHERE Name=N'MINI SUMO AMATEUR RC' ORDER BY CategoryId
);
DECLARE @EventId INT = (
    SELECT EventId FROM dbo.Events
    WHERE Name=N'UTA SUMO ROBOTICS CUP 2026' AND EditionYear=2026
);

IF @EventId IS NULL
BEGIN
    INSERT INTO dbo.Events(Name,EditionYear,RegistrationStart,RegistrationEnd,IsActive)
    VALUES(N'UTA SUMO ROBOTICS CUP 2026',2026,'2026-01-01',NULL,1);
    SET @EventId = CONVERT(INT,SCOPE_IDENTITY());
END
ELSE
BEGIN
    UPDATE dbo.Events SET IsActive=1 WHERE EventId=@EventId;
END;

IF NOT EXISTS (
    SELECT 1 FROM dbo.Tariffs
    WHERE EventId=@EventId AND CategoryId=@CategoryId AND IsActive=1
)
BEGIN
    INSERT INTO dbo.Tariffs(EventId,CategoryId,Amount,ValidFrom,ValidUntil,IsActive)
    VALUES(@EventId,@CategoryId,15.00,'2026-01-01',NULL,1);
END;
GO
