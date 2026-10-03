from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.product import Product
from app.models.user import User
from app.models.user_capability import UserCapability
from app.seed.seed import SEED_PRODUCTS, SEED_USERS


@pytest.mark.asyncio
async def test_clean_database_migration_and_demo_seed_are_complete_and_idempotent(monkeypatch):
    configured_url = make_url(get_settings().database_url)
    database_name = f"aiops_seed_test_{uuid.uuid4().hex[:12]}"
    admin_url = configured_url.set(drivername="postgresql", database="postgres")
    clean_url = configured_url.set(database=database_name)
    admin_url_string = admin_url.render_as_string(hide_password=False)
    clean_url_string = clean_url.render_as_string(hide_password=False)
    created_database = False
    engine = None

    try:
        with psycopg.connect(admin_url_string, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True

        environment = os.environ.copy()
        environment["DATABASE_URL"] = clean_url_string
        monkeypatch.setenv("DATABASE_URL", clean_url_string)
        for seed in SEED_USERS:
            password_variable = seed["password_field"].upper()
            environment[password_variable] = "CleanSeedPassword123!"
            monkeypatch.setenv(password_variable, "CleanSeedPassword123!")

        backend_dir = Path(__file__).resolve().parents[2]
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=backend_dir,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert migration.returncode == 0, "Alembic migration failed for the disposable clean database."

        first_seed = subprocess.run(
            [sys.executable, "-m", "app.seed.seed"],
            cwd=backend_dir,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert first_seed.returncode == 0, "The documented demo seed command failed on a clean database."
        engine = create_async_engine(clean_url_string, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            users = (await session.scalars(select(User).order_by(User.email))).all()
            assert {user.email for user in users} == {item["email"] for item in SEED_USERS}
            for user in users:
                expected = next(item for item in SEED_USERS if item["email"] == user.email)
                capabilities = await session.scalars(
                    select(UserCapability.capability).where(UserCapability.user_id == user.id)
                )
                assert set(capabilities.all()) == set(expected["capabilities"])
                assert user.is_admin is expected["is_admin"]

            expected_skus = {item["sku"] for item in SEED_PRODUCTS}
            products = (
                await session.scalars(select(Product).where(Product.sku.in_(expected_skus)))
            ).all()
            assert {product.sku for product in products} == expected_skus
            sku_1043 = next(product for product in products if product.sku == "SKU-1043")
            assert sku_1043.quantity_on_hand == 120
            assert any(product.quantity_on_hand < 10 for product in products)
            assert any(product.quantity_on_hand >= 50 for product in products)

            expected_documents = {
                "policy-leave-policy",
                "policy-expense-reimbursement-policy",
                "policy-inventory-policy",
                "policy-procurement-policy",
            }
            documents = (
                await session.scalars(
                    select(Document).where(
                        Document.document_identifier.in_(expected_documents),
                        Document.index_status == "indexed",
                    )
                )
            ).all()
            assert {document.document_identifier for document in documents} == expected_documents
            chunks = (
                await session.scalars(
                    select(DocumentChunk).where(DocumentChunk.document_id.in_([doc.id for doc in documents]))
                )
            ).all()
            assert chunks
            first_counts = (len(users), len(products), len(documents), len(chunks))

        second_seed = subprocess.run(
            [sys.executable, "-m", "app.seed.seed"],
            cwd=backend_dir,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert second_seed.returncode == 0, "The second demo seed command failed."
        async with factory() as session:
            repeated_users = (await session.scalars(select(User))).all()
            repeated_products = (
                await session.scalars(select(Product).where(Product.sku.in_([item["sku"] for item in SEED_PRODUCTS])))
            ).all()
            repeated_documents = (
                await session.scalars(
                    select(Document).where(
                        Document.document_identifier.in_(expected_documents),
                        Document.index_status == "indexed",
                    )
                )
            ).all()
            repeated_chunks = (
                await session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id.in_([doc.id for doc in repeated_documents])
                    )
                )
            ).all()
            assert (len(repeated_users), len(repeated_products), len(repeated_documents), len(repeated_chunks)) == first_counts
    finally:
        if engine is not None:
            await engine.dispose()
        if created_database:
            with psycopg.connect(admin_url_string, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))
