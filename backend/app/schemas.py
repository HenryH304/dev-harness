"""Pydantic schemas for API request/response models."""

import datetime
from typing import Any

from pydantic import BaseModel

# --- Ticket schemas ---


class TicketCreate(BaseModel):
    project: str
    title: str
    description: str
    acceptance_criteria: list[Any]
    priority: int


class TicketUpdate(BaseModel):
    project: str | None = None
    title: str | None = None
    description: str | None = None
    acceptance_criteria: list[Any] | None = None
    priority: int | None = None
    state: str | None = None
    branch_name: str | None = None
    worktree_path: str | None = None
    current_agent: str | None = None


class TicketResponse(BaseModel):
    id: int
    project: str
    title: str
    description: str
    acceptance_criteria: list[Any]
    priority: int
    state: str
    previous_state: str | None = None
    branch_name: str | None
    worktree_path: str | None
    current_agent: str | None
    assigned_at: datetime.datetime | None
    agent_attempts: int
    developer_timeouts: int
    reviewer_timeouts: int
    tester_timeouts: int
    merger_timeouts: int
    review_rejection_count: int
    tester_rejection_count: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class NoteResponse(BaseModel):
    id: int
    ticket_id: int
    author: str
    content: str
    note_type: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class TicketDetailResponse(TicketResponse):
    notes: list[NoteResponse] = []


# --- Note schemas ---


class NoteCreate(BaseModel):
    author: str
    content: str
    note_type: str


# --- Dependency schemas ---


class TransitionRequest(BaseModel):
    new_state: str
    agent_id: str | None = None
    note: str | None = None
    manual_override: bool = False


class AgentFailRequest(BaseModel):
    reason: str
    suggested_fixes: str | None = None
    rework_note: str | None = None


class DependencyCreate(BaseModel):
    depends_on_ticket_id: int


class DependencyResponse(BaseModel):
    id: int
    ticket_id: int
    depends_on_ticket_id: int
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class TicketSummary(BaseModel):
    id: int
    title: str
    state: str

    model_config = {"from_attributes": True}


class DependencyListResponse(BaseModel):
    blocked_by: list[TicketSummary] = []
    blocks: list[TicketSummary] = []
