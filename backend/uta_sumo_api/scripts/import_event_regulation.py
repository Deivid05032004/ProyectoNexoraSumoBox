"""Import a PDF into SQL Server as encrypted, versioned regulation content."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

from sqlalchemy import LargeBinary, bindparam, text

from app.core.crypto import encrypt_bytes
from app.services.regulation_storage import safe_filename, validate_pdf
from database import engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--event-id", required=True, type=int)
    parser.add_argument("--category-id", type=int, default=None,
                        help="Omitir para cargar un reglamento general del evento.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--publish", action="store_true",
                        help="Publica este reglamento y archiva la versión publicada anterior del mismo alcance.")
    args = parser.parse_args()
    if args.event_id <= 0 or (args.category_id is not None and args.category_id <= 0):
        parser.error("Los identificadores deben ser positivos.")
    title = args.title.strip()
    if not title or len(title) > 200:
        parser.error("El título debe tener entre 1 y 200 caracteres.")
    content = args.file.read_bytes()
    digest, page_count = validate_pdf(content)
    with engine.begin() as conn:
            if conn.execute(text("SELECT 1 FROM dbo.Events WHERE EventId=:id"),
                            {"id": args.event_id}).first() is None:
                raise SystemExit("El evento indicado no existe.")
            if args.category_id is not None and conn.execute(text(
                    "SELECT 1 FROM dbo.Categories WHERE CategoryId=:id"),
                    {"id": args.category_id}).first() is None:
                raise SystemExit("La categoría indicada no existe.")
            version = conn.execute(text("""
                SELECT ISNULL(MAX(VersionNumber),0)+1 FROM dbo.EventRegulations WITH (UPDLOCK,HOLDLOCK)
                WHERE EventId=:event AND (CategoryId=:category OR (CategoryId IS NULL AND :category IS NULL))
            """), {"event": args.event_id, "category": args.category_id}).scalar_one()
            regulation_id = conn.execute(text("""
                INSERT INTO dbo.EventRegulations
                  (EventId,CategoryId,Title,VersionNumber,OriginalFilename,MediaType,
                   FileSizeBytes,Sha256,StatusCode,EffectiveFrom,UploadedByUserId,FileContent)
                OUTPUT INSERTED.RegulationId
                VALUES(:event,:category,:title,:version,:filename,'application/pdf',
                       :size,:sha256,'DRAFT',:effective,NULL,:content)
            """).bindparams(bindparam("content", type_=LargeBinary)),
                {"event": args.event_id, "category": args.category_id, "title": title,
                 "version": version, "filename": safe_filename(args.file.name),
                 "size": len(content), "sha256": digest, "effective": date.today(),
                 "content": encrypt_bytes(content)}).scalar_one()
            conn.execute(text("""
                INSERT INTO dbo.EventRegulationHistory(RegulationId,ActorUserId,ActionCode,PreviousStatus,NewStatus)
                VALUES(:id,NULL,'CREATED',NULL,'DRAFT')
            """), {"id": regulation_id})
            if args.publish:
                prior = conn.execute(text("""
                    SELECT RegulationId FROM dbo.EventRegulations WITH (UPDLOCK,HOLDLOCK)
                    WHERE EventId=:event AND (CategoryId=:category OR (CategoryId IS NULL AND :category IS NULL))
                      AND StatusCode='PUBLISHED'
                """), {"event": args.event_id, "category": args.category_id}).scalars().all()
                for previous_id in prior:
                    conn.execute(text("""
                        UPDATE dbo.EventRegulations SET StatusCode='ARCHIVED' WHERE RegulationId=:id
                    """), {"id": previous_id})
                    conn.execute(text("""
                        INSERT INTO dbo.EventRegulationHistory
                          (RegulationId,ActorUserId,ActionCode,PreviousStatus,NewStatus)
                        VALUES(:id,NULL,'ARCHIVED','PUBLISHED','ARCHIVED')
                    """), {"id": previous_id})
                conn.execute(text("""
                    UPDATE dbo.EventRegulations SET StatusCode='PUBLISHED',PublishedAt=SYSUTCDATETIME()
                    WHERE RegulationId=:id
                """), {"id": regulation_id})
                conn.execute(text("""
                    INSERT INTO dbo.EventRegulationHistory
                      (RegulationId,ActorUserId,ActionCode,PreviousStatus,NewStatus)
                    VALUES(:id,NULL,'PUBLISHED','DRAFT','PUBLISHED')
                """), {"id": regulation_id})
    print(f"Reglamento importado: id={regulation_id}, version={version}, pages={page_count}, status={'PUBLISHED' if args.publish else 'DRAFT'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
