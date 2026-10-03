"""Development-safe email sending tool with DB-authoritative authorization."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.email_message import EmailMessage
from app.tools.authorization import ToolAuthorizationError, authorize_tool, ensure_thread_for_context
from app.tools.context import ToolContext


class EmailSendInput(BaseModel):
    """Validated email-send payload."""

    recipient: EmailStr
    subject: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, max_length=5000)
    idempotency_key: str = Field(..., min_length=1, max_length=128)


async def send_email(
    session: AsyncSession,
    context: ToolContext,
    recipient: str | EmailSendInput | None = None,
    subject: str | None = None,
    body: str | None = None,
    idempotency_key: str | None = None,
    **_ignored: object,
) -> dict[str, object]:
    """Persist a development email message only after the tool-specific capability check succeeds."""
    data: EmailSendInput
    if isinstance(recipient, EmailSendInput):
        data = recipient
    else:
        if recipient is None or subject is None or body is None or idempotency_key is None:
            raise ToolAuthorizationError("Recipient, subject, body, and idempotency key are required.")
        data = EmailSendInput(
            recipient=recipient,
            subject=subject,
            body=body,
            idempotency_key=idempotency_key,
        )

    user = await authorize_tool(session, context, "email:send")
    thread = await ensure_thread_for_context(session, context, user.id, f"Email to {data.recipient}")

    existing = await session.execute(
        select(EmailMessage).where(EmailMessage.idempotency_key == data.idempotency_key).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return {
            "status": "duplicate",
            "recipient": data.recipient,
            "subject": data.subject,
            "body": data.body,
            "idempotency_key": data.idempotency_key,
        }

    message = EmailMessage(
        recipient=str(data.recipient),
        subject=data.subject,
        body=data.body,
        sent_by=user.id,
        idempotency_key=data.idempotency_key,
    )
    session.add(message)
    await session.flush()

    audit = AuditLog(
        user_id=user.id,
        tool="email_send",
        arguments={
            "recipient": str(data.recipient),
            "subject": data.subject,
            "body": data.body,
            "idempotency_key": data.idempotency_key,
            "thread_id": str(thread.id),
        },
        outcome="executed",
        thread_id=thread.id,
    )
    session.add(audit)
    await session.commit()

    return {
        "status": "queued",
        "provider": "development-backend",
        "recipient": str(data.recipient),
        "subject": data.subject,
        "body": data.body,
        "idempotency_key": data.idempotency_key,
    }
