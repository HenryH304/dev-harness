"""Project management API endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Setting, Ticket

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectImportRequest(BaseModel):
    project_name: str
    prd_path: str


class ProjectImportResponse(BaseModel):
    imported_count: int


class ProjectInfo(BaseModel):
    name: str
    ticket_count: int


class ProjectListResponse(BaseModel):
    projects: list[ProjectInfo]
    active_priority_project: str


async def _get_session() -> AsyncSession:  # type: ignore[misc]
    """Get a database session using the app engine."""
    from app.main import engine

    async for session in get_session(engine):
        yield session


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
    projects = [
        ProjectInfo(name=row.project, ticket_count=row.ticket_count)
        for row in result.all()
    ]

    # Get active priority project from settings
    setting = await session.get(Setting, "active_priority_project")
    active = setting.value if setting else ""

    return ProjectListResponse(
        projects=projects, active_priority_project=active
    )


@router.post("/import", response_model=ProjectImportResponse)
async def import_project(
    req: ProjectImportRequest,
    session: AsyncSession = Depends(_get_session),
) -> ProjectImportResponse:
    """Import a Ralph prd.json file to create board tickets."""
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

    # Validate structure
    if "userStories" not in prd_data:
        raise HTTPException(
            status_code=400,
            detail="Invalid prd.json: missing userStories key",
        )

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

    return ProjectImportResponse(imported_count=count)
