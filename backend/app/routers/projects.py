"""Project management API endpoints."""

import json
import os
import subprocess

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


class ProjectCreateRequest(BaseModel):
    name: str
    repo_path: str
    create_if_missing: bool = False


class ProjectCreateResponse(BaseModel):
    name: str
    repo_path: str
    git_initialized: bool


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


@router.post("", response_model=ProjectCreateResponse, status_code=201)
async def create_project(
    req: ProjectCreateRequest,
    session: AsyncSession = Depends(_get_session),
) -> ProjectCreateResponse:
    """Create a new empty project (no tickets imported)."""
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="Project name is required")

    expanded_repo = os.path.expanduser(req.repo_path)

    if not os.path.isdir(expanded_repo):
        if not req.create_if_missing:
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

    existing = await session.get(Project, req.name)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Project '{req.name}' already exists",
        )

    # Initialise a git repo with a main branch if one doesn't already exist.
    # create_worktree requires `git worktree add ... main`, so the repo must
    # have at least one commit on main before any ticket can be picked up.
    git_initialized = False
    git_dir = os.path.join(expanded_repo, ".git")
    if not os.path.isdir(git_dir):
        try:
            git_env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "DevHarness",
                "GIT_AUTHOR_EMAIL": "devharness@local",
                "GIT_COMMITTER_NAME": "DevHarness",
                "GIT_COMMITTER_EMAIL": "devharness@local",
            }
            # Try modern git (2.28+) that supports -b; fall back for older git
            init_result = subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=expanded_repo,
                capture_output=True,
                text=True,
                env=git_env,
            )
            if init_result.returncode != 0:
                subprocess.run(
                    ["git", "init"],
                    cwd=expanded_repo,
                    capture_output=True,
                    env=git_env,
                )
                subprocess.run(
                    ["git", "checkout", "-b", "main"],
                    cwd=expanded_repo,
                    capture_output=True,
                    env=git_env,
                )

            # Empty initial commit so main exists as a real ref for worktrees
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", f"chore: initialise {req.name}"],
                cwd=expanded_repo,
                capture_output=True,
                env=git_env,
            )
            git_initialized = True
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to initialise git repository: {exc}",
            )

    try:
        session.add(Project(name=req.name, repo_path=expanded_repo))
        await session.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")

    return ProjectCreateResponse(name=req.name, repo_path=expanded_repo, git_initialized=git_initialized)


@router.post("/check-path", response_model=CheckPathResponse)
async def check_path(req: CheckPathRequest) -> CheckPathResponse:
    """Check whether a filesystem path exists."""
    expanded = os.path.expanduser(req.path)
    return CheckPathResponse(exists=os.path.isdir(expanded), expanded_path=expanded)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    session: AsyncSession = Depends(_get_session),
) -> ProjectListResponse:
    """List all projects with ticket counts and active priority project.

    Uses Project as the source of truth so projects with zero tickets appear.
    """
    from sqlalchemy import outerjoin

    # Left-join Project → Ticket to count tickets per project (including 0)
    stmt = (
        select(Project.name, Project.repo_path, func.count(Ticket.id).label("ticket_count"))
        .select_from(outerjoin(Project, Ticket, Project.name == Ticket.project))
        .group_by(Project.name, Project.repo_path)
        .order_by(Project.name)
    )
    result = await session.execute(stmt)
    projects = [
        ProjectInfo(name=row.name, ticket_count=row.ticket_count, repo_path=row.repo_path)
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
