"""API routes for the backend application."""

from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.authz import router as authz_router
from app.api.chat import router as chat_router

router = APIRouter()


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Return a simple application health response."""
    return {"status": "ok"}


router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(authz_router)
router.include_router(chat_router)
