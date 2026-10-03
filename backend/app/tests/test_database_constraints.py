from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import AuditLog, Document, DocumentChunk, EmailMessage, Order, Product, Thread, User, UserCapability

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as db_session:
        yield db_session
    await engine.dispose()


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}@example.com"


def unique_sku(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


async def _create_user(session, *, email: str, password_hash: str = "hashed_password") -> User:
    user = User(email=email, password_hash=password_hash, is_admin=False, is_active=True)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _create_product(session, *, sku: str, name: str = "Widget", quantity_on_hand: int = 10, price: Decimal = Decimal("10.99")) -> Product:
    product = Product(
        sku=sku,
        name=name,
        quantity_on_hand=quantity_on_hand,
        unit_price=price,
        supplier="Acme Supplies",
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


async def _create_thread(session, owner_user_id: int, title: str = "Test thread") -> Thread:
    thread = Thread(owner_user_id=owner_user_id, title=title)
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread


async def test_user_email_uniqueness(session) -> None:
    email = unique_email("duplicate-user")
    await _create_user(session, email=email)
    duplicate = User(email=email, password_hash="hash")
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_product_sku_uniqueness(session) -> None:
    sku = unique_sku("SKU-UNIQUE")
    await _create_product(session, sku=sku)
    duplicate = Product(
        sku=sku,
        name="Duplicate Product",
        quantity_on_hand=5,
        unit_price=Decimal("5.00"),
        supplier="Example",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_user_capability_uniqueness(session) -> None:
    user = await _create_user(session, email=unique_email("capability-user"))
    admin = await _create_user(session, email=unique_email("capability-admin"))
    first = UserCapability(user_id=user.id, capability="policy:read", granted_by=admin.id)
    second = UserCapability(user_id=user.id, capability="policy:read", granted_by=admin.id)
    session.add_all([first, second])
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_order_idempotency_key_uniqueness(session) -> None:
    user = await _create_user(session, email=unique_email("order-idem-user"))
    product = await _create_product(session, sku=unique_sku("SKU-IDEM"))
    key = f"duplicate-idem-{uuid4().hex[:8]}"
    first = Order(
        order_reference=f"PO-{uuid4().hex[:8]}",
        sku=product.sku,
        quantity=1,
        supplier="Acme Supplies",
        requested_by=user.id,
        idempotency_key=key,
    )
    second = Order(
        order_reference=f"PO-{uuid4().hex[:8]}",
        sku=product.sku,
        quantity=2,
        supplier="Acme Supplies",
        requested_by=user.id,
        idempotency_key=key,
    )
    session.add_all([first, second])
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_email_idempotency_key_uniqueness(session) -> None:
    sender = await _create_user(session, email=unique_email("email-sender"))
    key = f"email-id-{uuid4().hex[:8]}"
    first = EmailMessage(
        recipient="someone@example.com",
        subject="Hello",
        body="Body",
        sent_by=sender.id,
        idempotency_key=key,
    )
    second = EmailMessage(
        recipient="other@example.com",
        subject="Hello 2",
        body="Body 2",
        sent_by=sender.id,
        idempotency_key=key,
    )
    session.add_all([first, second])
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_document_chunk_position_uniqueness_per_document(session) -> None:
    user = await _create_user(session, email=unique_email("doc-user"))
    document = Document(
        title="Title",
        filename=f"title-{uuid4().hex[:8]}.txt",
        uploaded_by=user.id,
        index_status="pending",
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    first = DocumentChunk(document_id=document.id, chunk_text="Alpha", embedding_reference="ref-1", position=1)
    second = DocumentChunk(document_id=document.id, chunk_text="Beta", embedding_reference="ref-2", position=1)
    session.add_all([first, second])
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_product_quantity_cannot_be_negative(session) -> None:
    product = Product(
        sku=unique_sku("SKU-NEGATIVE"),
        name="Negative Stock Product",
        quantity_on_hand=-1,
        unit_price=Decimal("12.00"),
        supplier="Acme",
    )
    session.add(product)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_order_quantity_must_be_positive(session) -> None:
    user = await _create_user(session, email=unique_email("quantity-user"))
    product = await _create_product(session, sku=unique_sku("SKU-QUANTITY"))
    bad_order = Order(
        order_reference=f"PO-{uuid4().hex[:8]}",
        sku=product.sku,
        quantity=0,
        supplier="Acme Supplies",
        requested_by=user.id,
        idempotency_key=f"quantity-idem-{uuid4().hex[:8]}",
    )
    session.add(bad_order)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_thread_and_audit_log_relationship(session) -> None:
    user = await _create_user(session, email=unique_email("thread-audit-user"))
    thread = await _create_thread(session, owner_user_id=user.id)
    log = AuditLog(
        user_id=user.id,
        tool="inventory:read",
        arguments={"foo": "bar"},
        outcome="executed",
        thread_id=thread.id,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    assert log.thread_id == thread.id

    result = await session.execute(select(Thread).where(Thread.id == thread.id))
    stored = result.scalar_one()
    assert stored.owner_user_id == user.id


async def test_document_can_contain_multiple_chunks(session) -> None:
    user = await _create_user(session, email=unique_email("doc-owner"))
    document = Document(
        title="Multi chunk document",
        filename=f"multi-{uuid4().hex[:8]}.txt",
        uploaded_by=user.id,
        index_status="pending",
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    chunk_one = DocumentChunk(document_id=document.id, chunk_text="Chunk 1", embedding_reference="ref-1", position=1)
    chunk_two = DocumentChunk(document_id=document.id, chunk_text="Chunk 2", embedding_reference="ref-2", position=2)
    session.add_all([chunk_one, chunk_two])
    await session.commit()

    result = await session.execute(select(DocumentChunk).where(DocumentChunk.document_id == document.id))
    chunks = result.scalars().all()
    assert len(chunks) == 2


async def test_deleting_document_removes_chunks(session) -> None:
    user = await _create_user(session, email=unique_email("delete-doc-user"))
    document = Document(
        title="Delete me",
        filename=f"delete-{uuid4().hex[:8]}.txt",
        uploaded_by=user.id,
        index_status="pending",
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    session.add(
        DocumentChunk(
            document_id=document.id,
            chunk_text="Old chunk",
            embedding_reference="delete-ref",
            position=1,
        )
    )
    await session.commit()
    await session.delete(document)
    await session.commit()
    result = await session.execute(select(DocumentChunk).where(DocumentChunk.document_id == document.id))
    assert result.scalars().all() == []
