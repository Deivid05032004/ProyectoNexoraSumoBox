"""Payment instruction PDF generation and durable, private email delivery."""
from __future__ import annotations

import hashlib
from html import escape
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import (RECEIPT_STORAGE_DIR, SMTP_FROM_EMAIL, SMTP_FROM_NAME,
                             SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_STARTTLS,
                             SMTP_USERNAME)
from app.core.crypto import decrypt_text, encrypt_bytes


def build_payment_instruction_pdf(data: dict) -> bytes:
    """Render a structured, printable payment instruction (never a tax invoice)."""
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=22*mm, leftMargin=22*mm,
                            topMargin=20*mm, bottomMargin=20*mm,
                            title=f"Solicitud de pago {data['registration_code']}",
                            author=data["organization_name"])
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Subtle", parent=styles["BodyText"], textColor=colors.HexColor("#526174"), leading=15))
    story = [Paragraph(escape(str(data["organization_name"])), styles["Title"]),
             Paragraph(escape(str(data.get("form_title") or "Comprobante de solicitud e instrucciones de pago")), styles["Heading2"]),
             Paragraph("Este documento solicita el pago de la inscripción. No es una factura fiscal ni confirma que el pago fue realizado.", styles["Subtle"]),
             Spacer(1, 8*mm)]
    rows = [
        ["Evento", data["event_name"]], ["Inscripción", data["registration_code"]],
        ["Participante responsable", data["participant_name"]], ["Correo", data["email"]],
        ["Emitido", str(data["issued_at"])], ["Concepto", f"Inscripción — {data['category_name']}"],
        ["Total a pagar", f"{data['currency']} {data['amount']:.2f}"],
        ["Estado inicial", "PENDIENTE DE PAGO"],
    ]
    table = Table([[Paragraph(escape(str(c)), styles["BodyText"]) for c in row] for row in rows], colWidths=[48*mm, 112*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#edf2f7")),
        ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#17324d")),
        ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#d3dbe5")),
        ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8), ("TOPPADDING", (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
    ]))
    story.extend([table, Spacer(1, 8*mm), Paragraph("Instrucciones de pago", styles["Heading3"])])
    story.append(Paragraph(escape(data.get("form_instructions") or "").replace("\n", "<br/>"), styles["BodyText"]))
    story.append(Paragraph(escape(data.get("payment_instructions") or "Consulte con la organización los métodos de pago disponibles.").replace("\n", "<br/>"), styles["BodyText"]))
    methods = data.get("payment_methods") or []
    if methods:
        story.extend([Spacer(1, 3*mm), Paragraph(escape("Métodos disponibles: " + ", ".join(methods)), styles["BodyText"])])
    story.extend([Spacer(1, 5*mm), Paragraph("Luego de realizar la transferencia, ingrese a la plataforma y cargue el comprobante en la sección de pagos. El pago solo se considera validado después de la revisión administrativa.", styles["Subtle"])])
    if data.get("receipt_message"):
        story.extend([Spacer(1, 5*mm), Paragraph(escape(data["receipt_message"]).replace("\n", "<br/>"), styles["BodyText"])])
    contact = " · ".join(value for value in (data.get("contact_email"), data.get("contact_phone")) if value)
    if contact:
        story.extend([Spacer(1, 7*mm), Paragraph(escape("Contacto: " + contact), styles["Subtle"])])
    doc.build(story)
    return output.getvalue()


def store_pdf(registration_id: int, content: bytes) -> tuple[str, str]:
    key = f"payment-instruction-{registration_id}-{uuid4().hex}.pdf"
    root = RECEIPT_STORAGE_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / key).resolve()
    if target.parent != root:
        raise ValueError("Invalid private document path")
    staging = root / f".{uuid4().hex}.tmp"
    try:
        with staging.open("xb") as stream:
            stream.write(encrypt_bytes(content))
            stream.flush()
        staging.replace(target)
    except Exception:
        staging.unlink(missing_ok=True)
        raise
    return key, hashlib.sha256(content).hexdigest()


def deliver_outbox(db: Session, outbox_id: int) -> str:
    """Attempt delivery once and persist outcome; SMTP is optional in local dev."""
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        return "PENDING"
    row = db.execute(text("""
        SELECT o.RecipientCiphertext,o.Subject,o.BodyText,o.DeliveryStatus,
               d.StorageKey FROM dbo.EmailOutbox o
        LEFT JOIN dbo.RegistrationDocuments d ON d.DocumentId=o.DocumentId
        WHERE o.OutboxId=:id
    """), {"id": outbox_id}).mappings().first()
    if not row or row["DeliveryStatus"] == "SENT":
        return "SENT" if row else "FAILED"
    recipient = decrypt_text(row["RecipientCiphertext"])
    message = EmailMessage()
    message["From"] = formataddr((SMTP_FROM_NAME, SMTP_FROM_EMAIL))
    message["To"] = recipient
    message["Subject"] = decrypt_text(row["Subject"])
    message.set_content(decrypt_text(row["BodyText"]))
    if row["StorageKey"]:
        path = (RECEIPT_STORAGE_DIR.resolve() / row["StorageKey"]).resolve()
        if path.parent == RECEIPT_STORAGE_DIR.resolve() and path.is_file():
            from app.core.crypto import decrypt_bytes
            pdf = decrypt_bytes(path.read_bytes())
            message.add_attachment(pdf, maintype="application", subtype="pdf",
                                   filename="instrucciones-de-pago.pdf")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            if SMTP_STARTTLS:
                smtp.starttls()
            if SMTP_USERNAME:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)
        db.execute(text("""UPDATE dbo.EmailOutbox SET DeliveryStatus='SENT',Attempts=Attempts+1,
                         LastError=NULL,SentAt=SYSUTCDATETIME() WHERE OutboxId=:id"""), {"id": outbox_id})
        db.commit()
        return "SENT"
    except (OSError, smtplib.SMTPException):
        db.execute(text("""UPDATE dbo.EmailOutbox SET DeliveryStatus='FAILED',Attempts=Attempts+1,
                         LastError=N'No se pudo entregar el correo por SMTP.' WHERE OutboxId=:id"""), {"id": outbox_id})
        db.commit()
        return "FAILED"


def receipt_path(key: str) -> Path | None:
    root = RECEIPT_STORAGE_DIR.resolve()
    path = (root / key).resolve()
    return path if path.parent == root and path.is_file() else None
