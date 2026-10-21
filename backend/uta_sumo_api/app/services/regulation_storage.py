from __future__ import annotations

import hashlib
import os
import re
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader

from app.core.config import MAX_REGULATION_BYTES, REGULATION_STORAGE_DIR
from app.core.crypto import decrypt_bytes, encrypt_bytes


class InvalidRegulationPdf(ValueError):
    pass


def validate_pdf(content: bytes) -> tuple[str, int]:
    if not content or len(content) > MAX_REGULATION_BYTES:
        raise InvalidRegulationPdf("El reglamento está vacío o supera el tamaño máximo permitido.")
    if b"%PDF-" not in content[:1024] or b"%%EOF" not in content[-4096:]:
        raise InvalidRegulationPdf("El archivo no tiene una estructura PDF válida.")
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise InvalidRegulationPdf("No se aceptan PDF protegidos con contraseña.")
        page_count = len(reader.pages)
        if page_count < 1 or page_count > 500:
            raise InvalidRegulationPdf("El PDF debe contener entre 1 y 500 páginas.")
        root = reader.trailer["/Root"]
        if root.get("/AA") is not None:
            raise InvalidRegulationPdf("El PDF contiene acciones automáticas no permitidas.")
        if _unsafe_action(root.get("/OpenAction")):
            raise InvalidRegulationPdf("El PDF contiene acciones automáticas no permitidas.")
        names = root.get("/Names")
        if names and (names.get("/EmbeddedFiles") is not None or names.get("/JavaScript") is not None):
            raise InvalidRegulationPdf("El PDF contiene JavaScript o archivos adjuntos no permitidos.")
        if root.get("/AF") is not None:
            raise InvalidRegulationPdf("El PDF contiene archivos adjuntos no permitidos.")
        for page in reader.pages:
            if page.get("/AA") is not None:
                raise InvalidRegulationPdf("El PDF contiene acciones automáticas no permitidas.")
            for annotation in page.get("/Annots", []):
                annotation = annotation.get_object()
                if annotation.get("/AA") is not None or _unsafe_action(annotation.get("/A")):
                    raise InvalidRegulationPdf("El PDF contiene acciones automáticas no permitidas.")
    except InvalidRegulationPdf:
        raise
    except Exception as exc:
        raise InvalidRegulationPdf("No se pudo validar la estructura del PDF.") from exc
    return hashlib.sha256(content).hexdigest(), page_count


def _unsafe_action(action) -> bool:
    if action is None:
        return False
    try:
        action = action.get_object()
        return action.get("/S") in ("/JavaScript", "/Launch") or action.get("/JS") is not None
    except (AttributeError, TypeError):
        return True


def safe_filename(value: str | None) -> str:
    name = (value or "reglamento.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._")[:255]
    if not name or not name.lower().endswith(".pdf"):
        name = (name or "reglamento") + ".pdf"
    return name


def write_pdf(content: bytes) -> str:
    REGULATION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    root = REGULATION_STORAGE_DIR.resolve()
    key = f"{uuid4().hex}.pdf.enc"
    target = (root / key).resolve()
    if target.parent != root:
        raise RuntimeError("Ruta de almacenamiento de reglamento no válida.")
    staging = root / f".{key}.tmp"
    try:
        with staging.open("xb") as output:
            output.write(encrypt_bytes(content))
            output.flush()
            os.fsync(output.fileno())
        os.replace(staging, target)
        return key
    finally:
        staging.unlink(missing_ok=True)


def delete_pdf(key: str) -> None:
    path = get_pdf_path(key)
    if path:
        path.unlink(missing_ok=True)


def read_pdf(key: str) -> bytes | None:
    path = get_pdf_path(key)
    if path is None:
        return None
    try:
        return decrypt_bytes(path.read_bytes())
    except Exception:
        return None


def get_pdf_path(key: str) -> Path | None:
    if not re.fullmatch(r"[a-f0-9]{32}\.pdf\.enc", key):
        return None
    root = REGULATION_STORAGE_DIR.resolve()
    path = (root / key).resolve()
    return path if path.parent == root and path.is_file() else None
