"""Specification generation API — description → spec-writer → spec doc → story-writer → tickets."""

import asyncio
import datetime
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Project, SpecGeneration, Ticket, TicketDependency
from app.redis_client import publish_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/specs", tags=["specs"])


class CreateSpecRequest(BaseModel):
    project: str
    description: str


class AmendSpecRequest(BaseModel):
    amendment: str


class SpecGenerationOut(BaseModel):
    id: int
    project: str
    description: str
    spec_path: str | None = None
    spec_content: str | None = None
    status: str
    step: str | None = None
    imported_count: int | None = None
    error: str | None = None
    created_at: str
    completed_at: str | None = None


async def _get_session() -> AsyncSession:  # type: ignore[misc]
    from app.main import engine
    async for session in get_session(engine):
        yield session


def _to_out(rec: SpecGeneration, spec_content: str | None = None) -> SpecGenerationOut:
    return SpecGenerationOut(
        id=rec.id,
        project=rec.project,
        description=rec.description,
        spec_path=rec.spec_path,
        spec_content=spec_content,
        status=rec.status,
        step=rec.step,
        imported_count=rec.imported_count,
        error=rec.error,
        created_at=rec.created_at.isoformat(),
        completed_at=rec.completed_at.isoformat() if rec.completed_at else None,
    )


def _read_spec(spec_path: str | None) -> str | None:
    if not spec_path:
        return None
    p = Path(spec_path)
    return p.read_text() if p.is_file() else None


def _api_base_url() -> str:
    from app.main import config
    return f"http://localhost:{config.port}"


async def _import_stories(
    session: AsyncSession,
    project: str,
    stories: list[dict],
) -> int:
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
        await session.flush()
        story_id_to_ticket_id[story.get("id", "")] = ticket.id

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


async def _run_spec_writing(spec_id: int) -> None:
    """Background task: run spec-writer agent, write spec to project tasks folder."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.main import engine
    from app.ralph_runner import spawn_spec_writer

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        rec = await session.get(SpecGeneration, spec_id)
        if rec is None:
            return
        rec.status = "running"
        rec.step = "spec_writing"
        await session.commit()
        project = rec.project
        description = rec.description

    # Resolve spec path from project repo
    async with session_factory() as session:
        proj = await session.get(Project, project)
        if proj is None:
            async with session_factory() as s2:
                r = await s2.get(SpecGeneration, spec_id)
                if r:
                    r.status = "failed"
                    r.step = "spec_writing"
                    r.error = f"Project '{project}' not found"
                    r.completed_at = datetime.datetime.now(datetime.timezone.utc)
                    await s2.commit()
            return
        tasks_dir = Path(proj.repo_path) / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    spec_path = str(tasks_dir / f"spec-{ts}.md")

    try:
        result = await spawn_spec_writer(
            spec_id=spec_id,
            project=project,
            description=description,
            spec_path=spec_path,
            api_base_url=_api_base_url(),
        )
    except Exception as exc:
        logger.exception("spec_writing spawn failed for spec %d", spec_id)
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "failed"
                rec.step = "spec_writing"
                rec.error = f"Failed to spawn spec-writer: {exc}"
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    if not result.success:
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "failed"
                rec.step = "spec_writing"
                rec.error = f"spec-writer agent exited with code {result.exit_code}"
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    if not Path(spec_path).is_file():
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "failed"
                rec.step = "spec_writing"
                rec.error = f"spec-writer did not create {spec_path}"
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    async with session_factory() as session:
        rec = await session.get(SpecGeneration, spec_id)
        if rec:
            rec.status = "done"
            rec.step = "spec_writing"
            rec.spec_path = spec_path
            rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()


async def _run_amendment(spec_id: int, amendment: str) -> None:
    """Background task: re-run spec-writer with an amendment request."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.main import engine
    from app.ralph_runner import spawn_spec_writer

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        rec = await session.get(SpecGeneration, spec_id)
        if rec is None:
            return
        rec.status = "running"
        rec.step = "amending"
        rec.error = None
        await session.commit()
        project = rec.project
        description = rec.description
        spec_path = rec.spec_path

    existing_spec = _read_spec(spec_path)

    try:
        result = await spawn_spec_writer(
            spec_id=spec_id,
            project=project,
            description=description,
            spec_path=spec_path or "",
            api_base_url=_api_base_url(),
            amendment_request=amendment,
            existing_spec=existing_spec,
        )
    except Exception as exc:
        logger.exception("amendment spawn failed for spec %d", spec_id)
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "failed"
                rec.step = "amending"
                rec.error = f"Failed to spawn spec-writer for amendment: {exc}"
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    if not result.success:
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "failed"
                rec.step = "amending"
                rec.error = f"spec-writer amendment exited with code {result.exit_code}"
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    async with session_factory() as session:
        rec = await session.get(SpecGeneration, spec_id)
        if rec:
            rec.status = "done"
            rec.step = "amending"
            rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()


async def _run_conversion(spec_id: int) -> None:
    """Background task: run story-writer to convert spec → prd.json → import tickets."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.main import engine
    from app.ralph_runner import spawn_story_converter

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        rec = await session.get(SpecGeneration, spec_id)
        if rec is None:
            return
        rec.status = "running"
        rec.step = "converting"
        rec.error = None
        await session.commit()
        project = rec.project
        spec_path = rec.spec_path

    spec_content = _read_spec(spec_path)
    if not spec_content:
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "failed"
                rec.step = "converting"
                rec.error = f"Spec file not found or empty: {spec_path}"
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    import uuid
    prd_output_path = f"/tmp/{uuid.uuid4()}-prd.json"

    try:
        result = await spawn_story_converter(
            spec_id=spec_id,
            project=project,
            spec_content=spec_content,
            prd_output_path=prd_output_path,
        )
    except Exception as exc:
        logger.exception("story conversion spawn failed for spec %d", spec_id)
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "failed"
                rec.step = "converting"
                rec.error = f"Failed to spawn story-writer: {exc}"
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    if not result.success:
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "failed"
                rec.step = "converting"
                rec.error = f"story-writer exited with code {result.exit_code}"
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    # Parse generated prd.json
    try:
        prd_file = Path(prd_output_path)
        if not prd_file.exists():
            raise FileNotFoundError(f"story-writer did not create {prd_output_path}")
        prd_data = json.loads(prd_file.read_text())
        stories = prd_data.get("userStories", [])
    except Exception as exc:
        logger.exception("prd.json read failed for spec %d", spec_id)
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "failed"
                rec.step = "converting"
                rec.error = f"Failed to read generated prd.json: {exc}"
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()
        return

    # Import stories
    try:
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.step = "importing"
                await session.commit()

        async with session_factory() as session:
            imported = await _import_stories(session, project, stories)
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "done"
                rec.step = "importing"
                rec.imported_count = imported
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()

        await publish_event(
            "ticket:events",
            {
                "event_type": "spec_conversion_complete",
                "spec_id": spec_id,
                "project": project,
                "imported_count": imported,
            },
        )
    except Exception as exc:
        logger.exception("story import failed for spec %d", spec_id)
        async with session_factory() as session:
            rec = await session.get(SpecGeneration, spec_id)
            if rec:
                rec.status = "failed"
                rec.step = "importing"
                rec.error = f"Failed to import stories: {exc}"
                rec.completed_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()


@router.post("", response_model=SpecGenerationOut, status_code=201)
async def create_spec(
    body: CreateSpecRequest,
    session: AsyncSession = Depends(_get_session),
) -> SpecGenerationOut:
    """Start spec-writer agent for a feature description."""
    rec = SpecGeneration(
        project=body.project,
        description=body.description,
        status="pending",
    )
    session.add(rec)
    await session.commit()
    await session.refresh(rec)

    asyncio.create_task(
        _run_spec_writing(rec.id),
        name=f"spec-write-{rec.id}",
    )

    return _to_out(rec)


@router.get("/{spec_id}", response_model=SpecGenerationOut)
async def get_spec(
    spec_id: int,
    session: AsyncSession = Depends(_get_session),
) -> SpecGenerationOut:
    rec = await session.get(SpecGeneration, spec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Spec generation not found")
    return _to_out(rec, _read_spec(rec.spec_path))


@router.put("/{spec_id}/amend", response_model=SpecGenerationOut)
async def amend_spec(
    spec_id: int,
    body: AmendSpecRequest,
    session: AsyncSession = Depends(_get_session),
) -> SpecGenerationOut:
    rec = await session.get(SpecGeneration, spec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Spec generation not found")
    if rec.status not in ("done", "failed"):
        raise HTTPException(status_code=409, detail="Spec is not yet ready for amendment")

    asyncio.create_task(
        _run_amendment(rec.id, body.amendment),
        name=f"spec-amend-{rec.id}",
    )

    rec.status = "pending"
    rec.step = "amending"
    await session.commit()
    await session.refresh(rec)
    return _to_out(rec)


@router.post("/{spec_id}/convert", response_model=SpecGenerationOut)
async def convert_spec(
    spec_id: int,
    session: AsyncSession = Depends(_get_session),
) -> SpecGenerationOut:
    rec = await session.get(SpecGeneration, spec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Spec generation not found")
    if rec.status != "done" or not rec.spec_path:
        raise HTTPException(status_code=409, detail="Spec must be in 'done' state with a spec file")

    asyncio.create_task(
        _run_conversion(rec.id),
        name=f"spec-convert-{rec.id}",
    )

    rec.status = "pending"
    rec.step = "converting"
    await session.commit()
    await session.refresh(rec)
    return _to_out(rec)


@router.get("", response_model=list[SpecGenerationOut])
async def list_specs(
    session: AsyncSession = Depends(_get_session),
) -> list[SpecGenerationOut]:
    result = await session.execute(
        select(SpecGeneration).order_by(SpecGeneration.created_at.desc()).limit(50)
    )
    return [_to_out(r) for r in result.scalars().all()]
