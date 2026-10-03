"""Admin-only API endpoints for user, document, and activity management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.email_message import EmailMessage
from app.models.order import Order
from app.models.user import User
from app.models.user_capability import UserCapability, display_capability, normalize_capability
from app.policies.ingestion import chunk_policy_text
from app.schemas.auth import AdminUserResponse
from app.services.authorization import require_admin
from app.services.password import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminCreateUserRequest(BaseModel):
    """Request payload for creating a user."""

    email: EmailStr
    password: str = Field(..., min_length=8)
    is_admin: bool = False
    capabilities: list[str] = Field(default_factory=list)


class AdminPasswordRequest(BaseModel):
    """Request payload for setting a user's initial password."""

    password: str = Field(..., min_length=8)


class AdminCapabilityRequest(BaseModel):
    """Request payload for adding or removing a capability."""

    capability: str


class AdminDocumentUploadRequest(BaseModel):
    """Request payload for uploading admin policy content."""

    title: str | None = None
    filename: str | None = None
    content: str = ""
    source: str = "admin-upload"
    version: str = "1.0"


class AdminActivityResponse(BaseModel):
    """Nested admin activity payload."""

    model_config = ConfigDict(from_attributes=True)

    audit_trail: list[dict[str, object]]
    orders: list[dict[str, object]]
    email_messages: list[dict[str, object]]


async def _user_summary(session: AsyncSession, user: User) -> AdminUserResponse:
    capability_rows = await session.execute(
        select(UserCapability.capability).where(UserCapability.user_id == user.id)
    )
    caps = sorted({display_capability(row[0]) for row in capability_rows.fetchall()})
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        is_active=user.is_active,
        capabilities=caps,
    )


async def _ensure_capability(session: AsyncSession, user_id: int, capability: str, granted_by: int) -> None:
    normalized = normalize_capability(capability)
    if not normalized:
        return
    existing = await session.execute(
        select(UserCapability.id).where(
            UserCapability.user_id == user_id,
            UserCapability.capability == normalized,
        )
    )
    if existing.scalar_one_or_none() is None:
        session.add(
            UserCapability(
                user_id=user_id,
                capability=normalized,
                granted_by=granted_by,
            )
        )


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    _: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> list[AdminUserResponse]:
    """Return user summaries for administrators only."""
    users = (await session.execute(select(User).order_by(User.email.asc()))).scalars().all()
    return [await _user_summary(session, user) for user in users]


@router.post("/users", response_model=AdminUserResponse)
async def create_user(
    payload: AdminCreateUserRequest,
    current_user: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> AdminUserResponse:
    """Create a new user with a password and optional capabilities."""
    existing = await session.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists.")

    user = User(
        email=str(payload.email).lower(),
        password_hash=hash_password(payload.password),
        is_admin=payload.is_admin,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    for capability in payload.capabilities:
        await _ensure_capability(session, user.id, capability, current_user.id)

    await session.commit()
    return await _user_summary(session, user)


@router.post("/users/{user_id}/set-password", response_model=AdminUserResponse)
async def set_initial_password(
    user_id: int,
    payload: AdminPasswordRequest,
    current_user: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> AdminUserResponse:
    """Set a user's password and keep admin authorization at the backend boundary."""
    target_user = await session.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target_user.id == current_user.id and target_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrators may not reset their own password through this endpoint.")
    target_user.password_hash = hash_password(payload.password)
    await session.commit()
    return await _user_summary(session, target_user)


@router.post("/users/{user_id}/deactivate", response_model=AdminUserResponse)
async def deactivate_user(
    user_id: int,
    current_user: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> AdminUserResponse:
    """Deactivate a user, preventing future successful authentication."""
    target_user = await session.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target_user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrators may not deactivate their own account.")
    target_user.is_active = False
    await session.commit()
    return await _user_summary(session, target_user)


@router.post("/users/{user_id}/reactivate", response_model=AdminUserResponse)
async def reactivate_user(
    user_id: int,
    current_user: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> AdminUserResponse:
    """Reactivate an inactive user account."""
    target_user = await session.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if current_user.id == target_user.id and not target_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrators may not reactivate their own account through this endpoint.")
    target_user.is_active = True
    await session.commit()
    return await _user_summary(session, target_user)


@router.post("/users/{user_id}/capabilities", response_model=AdminUserResponse)
async def grant_capability(
    user_id: int,
    payload: AdminCapabilityRequest,
    current_user: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> AdminUserResponse:
    """Grant a capability to the target user from the authoritative database."""
    target_user = await session.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    await _ensure_capability(session, target_user.id, payload.capability, current_user.id)
    await session.commit()
    return await _user_summary(session, target_user)


@router.delete("/users/{user_id}/capabilities", response_model=AdminUserResponse)
async def revoke_capability(
    user_id: int,
    payload: AdminCapabilityRequest,
    current_user: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> AdminUserResponse:
    """Revoke a capability from the target user."""
    target_user = await session.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    normalized = normalize_capability(payload.capability)
    await session.execute(
        UserCapability.__table__.delete().where(
            UserCapability.user_id == target_user.id,
            UserCapability.capability == normalized,
        )
    )
    await session.commit()
    return await _user_summary(session, target_user)


@router.get("/documents", response_model=list[dict[str, object]])
async def list_documents(
    _: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, object]]:
    """List uploaded policy documents and their indexing state."""
    documents = (await session.execute(select(Document).order_by(Document.uploaded_at.desc()))).scalars().all()
    return [
        {
            "id": document.id,
            "title": document.title,
            "filename": document.filename,
            "document_identifier": document.document_identifier,
            "source": document.source,
            "version": document.version,
            "uploaded_by": document.uploaded_by,
            "uploaded_at": document.uploaded_at.isoformat(),
            "index_status": document.index_status,
        }
        for document in documents
    ]


@router.post("/documents", response_model=dict[str, object])
async def upload_document(
    payload: AdminDocumentUploadRequest,
    current_user: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """Upload or replace a policy document and make it searchable immediately."""
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document content is required.")

    base_title = payload.title or (payload.filename or "Uploaded policy").strip() or "Uploaded policy"
    document_identifier = f"admin-{uuid.uuid4().hex[:12]}"
    document = Document(
        title=base_title,
        filename=payload.filename or f"{base_title.lower().replace(' ', '-')}.md",
        document_identifier=document_identifier,
        version=payload.version,
        source=payload.source,
        uploaded_by=current_user.id,
        index_status="indexed",
        content=content,
    )
    session.add(document)
    await session.flush()

    for position, chunk_text in enumerate(chunk_policy_text(content), start=1):
        session.add(
            DocumentChunk(
                document_id=document.id,
                chunk_text=chunk_text,
                embedding_reference=f"{document_identifier}-chunk-{position}",
                position=position,
            )
        )
    await session.commit()
    return {
        "id": document.id,
        "title": document.title,
        "filename": document.filename,
        "document_identifier": document.document_identifier,
        "index_status": document.index_status,
        "chunks": len(chunk_policy_text(content)),
    }


@router.delete("/documents/{document_id}", response_model=dict[str, object])
async def remove_document(
    document_id: int,
    _: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """Hide a document from policy results without deleting its DB record."""
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    document.index_status = "deleted"
    await session.commit()
    return {"id": document.id, "status": "deleted"}


@router.get("/documents/indexing-status", response_model=dict[str, object])
async def indexing_status(
    _: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """Return the current document indexing status summary."""
    rows = (await session.execute(select(Document.index_status, Document.id))).all()
    summary = {status_name: 0 for status_name in ["pending", "indexed", "failed", "deleted"]}
    for index_status, _ in rows:
        if index_status in summary:
            summary[index_status] += 1
    return {"statuses": summary, "total_documents": sum(summary.values())}


@router.get("/activity", response_model=AdminActivityResponse)
async def admin_activity(
    _: User = Depends(require_admin()),
    session: AsyncSession = Depends(get_db_session),
) -> AdminActivityResponse:
    """Expose audit, order, and sent-email activity in newest-first order."""
    audit_rows = (await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()))).scalars().all()
    order_rows = (await session.execute(select(Order).order_by(Order.created_at.desc()))).scalars().all()
    email_rows = (await session.execute(select(EmailMessage).order_by(EmailMessage.sent_at.desc()))).scalars().all()

    return AdminActivityResponse(
        audit_trail=[
            {
                "id": item.id,
                "user_id": item.user_id,
                "tool": item.tool,
                "arguments": item.arguments,
                "outcome": item.outcome,
                "thread_id": item.thread_id,
                "created_at": item.created_at.isoformat(),
            }
            for item in audit_rows
        ],
        orders=[
            {
                "id": item.id,
                "order_reference": item.order_reference,
                "sku": item.sku,
                "quantity": item.quantity,
                "supplier": item.supplier,
                "requested_by": item.requested_by,
                "created_at": item.created_at.isoformat(),
            }
            for item in order_rows
        ],
        email_messages=[
            {
                "id": item.id,
                "recipient": item.recipient,
                "subject": item.subject,
                "body": item.body,
                "sent_by": item.sent_by,
                "sent_at": item.sent_at.isoformat(),
            }
            for item in email_rows
        ],
    )
