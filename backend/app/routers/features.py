"""Feature generation API — description → prd-writer agent → tickets."""

import asyncio
import datetime
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import FeatureRequest, Ticket, TicketDependency
from app.redis_client import publish_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/features", tags=["features"])


class GenerateRequest(BaseModel):
    project: str
    description: str


class FeatureRequestOut(BaseModel):
    id: int
    project: str
    description: str
    status: str
    output_path: str | None = None
    imported_count: int | None = None
    error: str | None = None
    created_at: str
    completed_at: str | None = None


async def _get_session() -> AsyncSession:  # type: ignore[misc]
    from app.main import engine
    async for session in get_session(engine):
        yield session


def _to_out(req: FeatureRequest) -> FeatureRequestOut:
    return FeatureRequestOut(
        id=req.id,
        project=req.project,
        description=req.description,
        status=req.status,
        output_path=req.output_path,
        imported_count=req.imported_count,
        error=req.error,
        created_at=req.created_at.isoformat(),
        completed_at=req.completed_at.isoformat() if req.completed_at else None,
    )


async def _import_stories(
    session: AsyncSession,
    project: str,
    stories: list[dict],
) -> int:
    """Create Ticket rows and TicketDependency rows from the prd.json userStories.

    Returns the number of tickets created.
    """
    story_id_to_ticket_id: dict[str, int] = {}

    for story in stories:
        ticket = Ticket(
            project=project,
            title=story.get("title", ""),
            description=story.get("description", ""),
            acceptance_criteria=story.get("acceptanceCriteria", []),
            priority=story.get("priority", 0),
            state="to_do",
        )
        session.add(ticket)
        await session.flush()  # populate ticket.id
        story_id_to_ticket_id[story.get("id", "")] = ticket.id

    # Create dependency records
    for story in stories:
        deps = story.get("dependencies", [])
        ticket_id = story_id_to_ticket_id.get(story.get("id", ""))
        if not ticket_id:
            continue
        for dep_story_id in deps:
            dep_ticket_id = story_id_to_ticket_id.get(dep_story_id)
            if dep_ticket_id:
                session.add(
                    TicketDependency(
                        ticket_id=ticket_id,
                        depends_on_ticket_id=dep_ticket_id,
                    )
                )

    return len(story_id_to_ticket_id)


async def _run_generation(feature_request_id: int) -> None:
    """Background task: run the prd-writer agent and import the result."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.main import engine
    from app.ralph_runner import spawn_prd_writer

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Mark running
    async with session_factory() as session:
        req = await session.get(FeatureRequest, feature_request_id)
        if req is None:
            return
        req.status = "running"
        await session.commit()
        project = req.project
        description = req.description

    ts = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    output_path = f"/tmp/{project}-{ts}-prd.json"

    # Spawn ralph
    try:
        result = await spawn_prd_writer(
            feature_request_id=feature_request_id,
            project=project,
            description=description,
            output_path=output_path,
        )
    except Exception as exc:
        async with session_factory() as session:
            req = await session.get(FeatureRequest, feature_request_id)
            if req:
                req.status = "failed"
                req.error = str(exc)
                req.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    if not result.success:
        async with session_factory() as session:
            req = await session.get(FeatureRequest, feature_request_id)
            if req:
                req.status = "failed"
                req.error = f"ralph exited with code {result.exit_code}"
                req.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    # Parse generated prd.json
    try:
        output_file = Path(output_path)
        if not output_file.exists():
            raise FileNotFoundError(f"Agent did not create {output_path}")
        prd_data = json.loads(output_file.read_text())
        stories = prd_data.get("userStories", [])
    except Exception as exc:
        async with session_factory() as session:
            req = await session.get(FeatureRequest, feature_request_id)
            if req:
                req.status = "failed"
                req.error = f"Failed to read generated prd.json: {exc}"
                req.output_path = output_path
                req.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    # Import stories into DB
    try:
        async with session_factory() as session:
            imported = await _import_stories(session, project, stories)
            req = await session.get(FeatureRequest, feature_request_id)
            if req:
                req.status = "done"
                req.output_path = output_path
                req.imported_count = imported
                req.completed_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()

        await publish_event(
            "ticket:events",
            {
                "event_type": "feature_generation_complete",
                "feature_request_id": feature_request_id,
                "project": project,
                "imported_count": imported,
            },
        )
    except Exception as exc:
        logger.error("Feature import failed for request %d: %s", feature_request_id, exc)
        async with session_factory() as session:
            req = await session.get(FeatureRequest, feature_request_id)
            if req:
                req.status = "failed"
                req.error = f"Import failed: {exc}"
                req.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()


@router.post("/generate", response_model=FeatureRequestOut)
async def generate_feature(
    body: GenerateRequest,
    session: AsyncSession = Depends(_get_session),
) -> FeatureRequestOut:
    """Submit a feature description for autonomous PRD generation.

    Returns immediately with a pending request.  The prd-writer agent runs
    in the background; a 'feature_generation_complete' WebSocket event fires
    when done and tickets are ready on the board.
    """
    req = FeatureRequest(
        project=body.project,
        description=body.description,
        status="pending",
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)

    asyncio.create_task(
        _run_generation(req.id),
        name=f"feature-gen-{req.id}",
    )

    return _to_out(req)


@router.get("", response_model=list[FeatureRequestOut])
async def list_feature_requests(
    session: AsyncSession = Depends(_get_session),
) -> list[FeatureRequestOut]:
    """Return all feature generation requests, newest first."""
    from sqlalchemy import select
    result = await session.execute(
        select(FeatureRequest).order_by(FeatureRequest.created_at.desc()).limit(50)
    )
    return [_to_out(r) for r in result.scalars().all()]


@router.get("/{feature_id}", response_model=FeatureRequestOut)
async def get_feature_request(
    feature_id: int,
    session: AsyncSession = Depends(_get_session),
) -> FeatureRequestOut:
    req = await session.get(FeatureRequest, feature_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Feature request not found")
    return _to_out(req)
