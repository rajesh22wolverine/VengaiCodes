# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Project Schemas
#  schemas/project.py — Pydantic request/response schemas for projects
# ═══════════════════════════════════════════════════════════════

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ───────────────────────────────────────────────
#  Create Project
# ───────────────────────────────────────────────
class CreateProjectRequest(BaseModel):
    """Request to start a new project from a raw idea description."""
    name: str = Field(..., min_length=1, max_length=255)
    raw_idea: str = Field(..., min_length=1, max_length=5000)
    description: Optional[str] = None


# ───────────────────────────────────────────────
#  Project Response — mirrors models/project.py Project
# ───────────────────────────────────────────────
class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    raw_idea: Optional[str] = None
    category: str
    complexity: Optional[str] = None
    platforms: list[str] = []
    status: str
    current_phase: str
    progress_percent: float
    phases_completed: list[str] = []
    understanding_score: float
    estimated_build_time_minutes: Optional[int] = None
    thumbnail_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_db(cls, project) -> "ProjectResponse":
        return cls(
            id=project.id,
            name=project.name,
            description=project.description,
            raw_idea=project.raw_idea,
            category=project.category.value if hasattr(project.category, "value") else project.category,
            complexity=(project.complexity.value if hasattr(project.complexity, "value") else project.complexity)
                if project.complexity else None,
            platforms=project.platforms or [],
            status=project.status.value if hasattr(project.status, "value") else project.status,
            current_phase=project.current_phase.value if hasattr(project.current_phase, "value") else project.current_phase,
            progress_percent=project.progress_percent,
            phases_completed=project.phases_completed or [],
            understanding_score=project.understanding_score,
            estimated_build_time_minutes=project.estimated_build_time_minutes,
            thumbnail_url=project.thumbnail_url,
            created_at=project.created_at,
            updated_at=project.updated_at,
            completed_at=project.completed_at,
        )


# ───────────────────────────────────────────────
#  List Response
# ───────────────────────────────────────────────
class ProjectListResponse(BaseModel):
    success: bool = True
    projects: list[ProjectResponse]
    total: int


# ───────────────────────────────────────────────
#  Single Project Response
# ───────────────────────────────────────────────
class ProjectDetailResponse(BaseModel):
    success: bool = True
    project: ProjectResponse


# ───────────────────────────────────────────────
#  Delete Response
# ───────────────────────────────────────────────
class DeleteProjectResponse(BaseModel):
    success: bool = True
    message: str = "Project deleted successfully."
