"""Email dispatch node using Gmail SMTP with dry-run support and SQLite tracking."""

import email.message
import logging
from pathlib import Path
import smtplib
from typing import Optional

from config import settings
from db.database import log_audit, record_sent_email, update_opportunity_status
from pipeline.state import OpportunityPipelineState

logger = logging.getLogger(__name__)


def send_email_via_smtp(
    to_email: str,
    subject: str,
    body: str,
    sender_email: Optional[str] = None,
    app_password: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    attachment_path: Optional[Path] = None,
) -> None:
    """Send a plain text email via Gmail SMTP with TLS and optional PDF attachment."""
    user = sender_email or settings.GMAIL_USER
    password = app_password or settings.GMAIL_APP_PASSWORD
    host = smtp_host or settings.SMTP_HOST
    port = smtp_port or settings.SMTP_PORT

    if not user or not password:
        raise ValueError("GMAIL_USER or GMAIL_APP_PASSWORD is not configured in .env")

    msg = email.message.EmailMessage()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    # Attach resume PDF if available
    pdf_target = attachment_path or (settings.BASE_DIR / "profile" / "resume.pdf")
    if pdf_target.exists():
        try:
            with open(pdf_target, "rb") as f:
                pdf_data = f.read()
            msg.add_attachment(
                pdf_data,
                maintype="application",
                subtype="pdf",
                filename="Anurag_Banerjee_Resume.pdf",
            )
            logger.info(f"Attached resume PDF ({len(pdf_data)} bytes) to email for {to_email}")
        except Exception as e:
            logger.warning(f"Failed to attach resume PDF: {e}")

    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, password)
        server.send_message(msg)

    logger.info(f"Successfully sent email to {to_email} via Gmail SMTP")


async def execute_outreach_send(state: OpportunityPipelineState) -> OpportunityPipelineState:
    """Execute outreach sending (or dry-run simulation) and record sent history."""
    db_path = Path(state.db_path) if state.db_path else None
    recipient = state.manually_provided_email or state.contact_email
    if not recipient or recipient == "missing":
        state.error_message = "Cannot send email: No recipient email address available."
        logger.error(state.error_message)
        return state

    subject = state.edited_subject or state.draft_subject
    body = state.edited_body or state.draft_body

    if settings.DRY_RUN:
        logger.info(
            f"[DRY_RUN] Simulated email dispatch to {recipient} ({state.company_name}):\n"
            f"Subject: {subject}\nBody:\n{body}"
        )
        log_audit(
            event_type="email_simulated",
            message=f"[DRY_RUN] Email simulated for {state.company_name} ({recipient})",
            payload={"opportunity_id": state.opportunity_id, "recipient": recipient, "subject": subject},
            db_path=db_path,
        )
    else:
        try:
            send_email_via_smtp(
                to_email=recipient,
                subject=subject,
                body=body,
            )
            log_audit(
                event_type="email_dispatched",
                message=f"Live email sent to {recipient} ({state.company_name})",
                payload={"opportunity_id": state.opportunity_id, "recipient": recipient, "subject": subject},
                db_path=db_path,
            )
        except Exception as e:
            state.error_message = f"Failed to send email via SMTP: {e}"
            logger.error(state.error_message, exc_info=True)
            return state

    # Record into sent_history table in SQLite
    sent_id = record_sent_email(
        opportunity_id=state.opportunity_id,
        draft_id=state.draft_id,
        contact_id=state.contact_id,
        recipient_email=recipient,
        subject=subject,
        body=body,
        notes="Sent via Gmail SMTP (Dry Run)" if settings.DRY_RUN else "Sent via Gmail SMTP",
        db_path=db_path,
    )

    update_opportunity_status(state.opportunity_id, "sent", db_path=db_path)
    state.is_sent = True
    return state
