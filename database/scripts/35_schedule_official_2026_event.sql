USE UTA_SUMO_ROBOTICS_CUP;
GO

/* The official 2026 event is already enabled for participant-facing pages.
   Move a legacy DRAFT row to SCHEDULED so admin/public status agrees. */
DECLARE @EventId INT = (
    SELECT TOP (1) EventId
    FROM dbo.Events
    WHERE Name=N'UTA SUMO ROBOTICS CUP 2026' AND EditionYear=2026 AND IsActive=1
    ORDER BY EventId
);

IF @EventId IS NOT NULL
   AND EXISTS (SELECT 1 FROM dbo.Events WHERE EventId=@EventId AND CompetitionStatus='DRAFT')
BEGIN
    UPDATE dbo.Events
    SET CompetitionStatus='SCHEDULED', IsActive=1
    WHERE EventId=@EventId AND CompetitionStatus='DRAFT';

    IF NOT EXISTS (
        SELECT 1 FROM dbo.EventStatusHistory
        WHERE EventId=@EventId AND PreviousStatus='DRAFT' AND NewStatus='SCHEDULED'
          AND Reason=N'Normalización del evento oficial UTA SUMO ROBOTICS CUP 2026.'
    )
        INSERT dbo.EventStatusHistory(EventId,PreviousStatus,NewStatus,Reason,ActorUserId)
        VALUES(@EventId,'DRAFT','SCHEDULED',
               N'Normalización del evento oficial UTA SUMO ROBOTICS CUP 2026.',NULL);

    DECLARE @ActorUserId INT = (
        SELECT TOP (1) u.UserId
        FROM dbo.Users u JOIN dbo.Roles r ON r.RoleId=u.RoleId
        WHERE r.Code='ADMIN' AND u.IsActive=1
        ORDER BY u.UserId
    );
    IF @ActorUserId IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM dbo.CompetitionEventStatusHistory
        WHERE EventId=@EventId AND PreviousStatus='DRAFT' AND NewStatus='SCHEDULED'
          AND Reason=N'Normalización del evento oficial UTA SUMO ROBOTICS CUP 2026.'
    )
        INSERT dbo.CompetitionEventStatusHistory(EventId,PreviousStatus,NewStatus,ChangedByUserId,Reason)
        VALUES(@EventId,'DRAFT','SCHEDULED',@ActorUserId,
               N'Normalización del evento oficial UTA SUMO ROBOTICS CUP 2026.');
END;
GO
