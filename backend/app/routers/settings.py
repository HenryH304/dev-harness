"""Settings API endpoints."""

from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    settings: dict[str, str]


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, str]


class SettingsUpdateResponse(BaseModel):
    updated_count: int


async def _get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session using the app engine."""
    from app.main import engine

    async for session in get_session(engine):
        yield session


@router.get("", response_model=SettingsResponse)
async def get_settings(
    session: AsyncSession = Depends(_get_session),
) -> SettingsResponse:
    """Return all current settings as key-value pairs."""
    result = await session.execute(select(Setting))
    rows = result.scalars().all()
    settings_dict: dict[str, str] = {row.key: row.value for row in rows}
    return SettingsResponse(settings=settings_dict)


@router.patch("", response_model=SettingsUpdateResponse)
async def update_settings(
    req: SettingsUpdateRequest,
    session: AsyncSession = Depends(_get_session),
) -> SettingsUpdateResponse:
    """Update one or more settings values. Creates if not exists."""
    for key, value in req.settings.items():
        if key.startswith("max_agents_") and key != "max_agents_system":
            try:
                if int(value) < 1:
                    raise HTTPException(
                        status_code=422,
                        detail=f"'{key}' must be >= 1 — setting it to 0 disables the agent type entirely",
                    )
            except ValueError:
                raise HTTPException(status_code=422, detail=f"'{key}' must be an integer")

    count = 0
    for key, value in req.settings.items():
        # Check if setting exists
        result = await session.execute(select(Setting).where(Setting.key == key))
        existing: Setting | None = result.scalar_one_or_none()
        if existing is not None:
            existing.value = value
        else:
            session.add(Setting(key=key, value=value))
        count += 1

    await session.commit()
    return SettingsUpdateResponse(updated_count=count)
