"""Project management API endpoints."""

import json
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Project, Setting, Ticket
from app.redis_client import publish_event

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectImportRequest(BaseModel):
    project_name: str
    prd_path: str
    repo_path: str
    create_repo_if_missing: bool = False


class ProjectImportResponse(BaseModel):
    imported_count: int


class ProjectInfo(BaseModel):
    name: str
    ticket_count: int
    repo_path: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectInfo]
    active_priority_project: str


class CheckPathRequest(BaseModel):
    path: str


class CheckPathResponse(BaseModel):
    exists: bool
    expanded_path: str


async def _get_session() -> AsyncSession:  # type: ignore[misc]
    """Get a database session using the app engine."""
    from app.main import engine

    async for session in get_session(engine):
        yield session


@router.post("/check-path", response_model=CheckPathResponse)
async def check_path(req: CheckPathRequest) -> CheckPathResponse:
    """Check whether a filesystem path exists."""
    expanded = os.path.expanduser(req.path)
    return CheckPathResponse(exists=os.path.isdir(expanded), expanded_path=expanded)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    session: AsyncSession = Depends(_get_session),
) -> ProjectListResponse:
    """List all projects with ticket counts and active priority project."""
    stmt = (
        select(Ticket.project, func.count(Ticket.id).label("ticket_count"))
        .group_by(Ticket.project)
        .order_by(Ticket.project)
    )
    result = await session.execute(stmt)
    project_records_result = await session.execute(select(Project))
    repo_paths = {p.name: p.repo_path for p in project_records_result.scalars().all()}
    projects = [
        ProjectInfo(name=row.project, ticket_count=row.ticket_count, repo_path=repo_paths.get(row.project, ""))
        for row in result.all()
    ]

    setting = await session.get(Setting, "active_priority_project")
    active = setting.value if setting else ""

    return ProjectListResponse(projects=projects, active_priority_project=active)


@router.post("/import", response_model=ProjectImportResponse)
async def import_project(
    req: ProjectImportRequest,
    session: AsyncSession = Depends(_get_session),
) -> ProjectImportResponse:
    """Import a Ralph prd.json file to create board tickets."""
    # Expand and validate repo_path
    expanded_repo = os.path.expanduser(req.repo_path)
    if not os.path.isdir(expanded_repo):
        if not req.create_repo_if_missing:
            raise HTTPException(
                status_code=422,
                detail=f"Repo path does not exist: {expanded_repo}",
            )
        try:
            os.makedirs(expanded_repo, exist_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create repo path: {exc}",
            )

    # Read and parse prd.json
    try:
        with open(req.prd_path) as f:
            prd_data = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail=f"File not found: {req.prd_path}")
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400, detail=f"Invalid JSON in file: {req.prd_path}"
        )

    if "userStories" not in prd_data:
        raise HTTPException(
            status_code=400,
            detail="Invalid prd.json: missing userStories key",
        )

    # Upsert Project record with repo_path
    existing_project = await session.get(Project, req.project_name)
    if existing_project is not None:
        existing_project.repo_path = expanded_repo
    else:
        session.add(Project(name=req.project_name, repo_path=expanded_repo))

    stories = prd_data["userStories"]
    count = 0

    for story in stories:
        ticket = Ticket(
            project=req.project_name,
            title=story.get("title", ""),
            description=story.get("description", ""),
            acceptance_criteria=story.get("acceptanceCriteria", []),
            priority=story.get("priority", 0),
            state="to_do",
        )
        session.add(ticket)
        count += 1

    await session.commit()

    if count > 0:
        await publish_event(
            "ticket:events",
            {"event_type": "developer_work_available", "project": req.project_name, "count": count},
        )

    return ProjectImportResponse(imported_count=count)
