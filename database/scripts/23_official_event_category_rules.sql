USE UTA_SUMO_ROBOTICS_CUP;
GO

/* Official UTA SUMO ROBOTICS CUP 2026 Mini Sumo Amateur RC rules. This affects
   new registrations only; historical registrations, payments and amounts stay intact. */
UPDATE ec SET MinParticipants=2,MaxParticipants=2,MinCoaches=0,MaxCoaches=0,
  UpdatedAt=SYSUTCDATETIME()
FROM dbo.EventCategories ec
JOIN dbo.Events e ON e.EventId=ec.EventId
JOIN dbo.Categories c ON c.CategoryId=ec.CategoryId
WHERE e.Name=N'UTA SUMO ROBOTICS CUP 2026' AND e.EditionYear=2026
  AND c.Name=N'MINI SUMO AMATEUR RC';
GO
