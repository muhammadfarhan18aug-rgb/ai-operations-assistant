"""API routes for the backend application."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Return a simple application health response."""
    return {"status": "ok"}
