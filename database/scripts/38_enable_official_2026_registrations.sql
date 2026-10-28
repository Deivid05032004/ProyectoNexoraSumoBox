USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Keep public enrollment enabled for the official 2026 edition. Competition
   status (for example PAUSED) is intentionally independent from registration. */
DECLARE @EventId INT = (
    SELECT TOP (1) EventId
    FROM dbo.Events
    WHERE Name=N'UTA SUMO ROBOTICS CUP 2026' AND EditionYear=2026
    ORDER BY EventId
);

IF @EventId IS NOT NULL
BEGIN
    UPDATE dbo.Events
    SET IsActive=1,RegistrationEnd=NULL
    WHERE EventId=@EventId AND CompetitionStatus NOT IN ('FINISHED','CANCELLED');

    IF EXISTS (SELECT 1 FROM dbo.EventRegistrationConfigs WHERE EventId=@EventId)
        UPDATE dbo.EventRegistrationConfigs SET IsEnabled=1 WHERE EventId=@EventId;
    ELSE
        INSERT dbo.EventRegistrationConfigs(EventId,OrganizationName,FormTitle,Currency,IsEnabled)
        VALUES(@EventId,N'UTA SUMO ROBOTICS CUP 2026',
               N'Inscripción UTA SUMO ROBOTICS CUP 2026','USD',1);
END;
GO
