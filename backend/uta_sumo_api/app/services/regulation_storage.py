from __future__ import annotations

import hashlib
import re
from io import BytesIO

from pypdf import PdfReader

from app.core.config import MAX_REGULATION_BYTES
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


def encrypt_regulation_pdf(content: bytes) -> bytes:
    return encrypt_bytes(content)


def decrypt_regulation_pdf(content: bytes) -> bytes:
    return decrypt_bytes(content)
