"""Password hashing and verification helpers."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Hash a user password using Argon2id."""
    if not password:
        raise ValueError("Password must not be empty.")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a cleartext password against a stored Argon2 hash."""
    if not password or not password_hash:
        return False

    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False
