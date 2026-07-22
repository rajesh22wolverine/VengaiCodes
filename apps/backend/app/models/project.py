# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Project Database Model
#  models/project.py — SQLAlchemy ORM model for projects
#  Every project a user builds goes through full SDLC phases
# ═══════════════════════════════════════════════════════════════

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float,
    ForeignKey, Integer, String, Text, JSON,
    Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


# ───────────────────────────────────────────────
#  Enums
# ───────────────────────────────────────────────
class ProjectStatus(str, PyEnum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    DELETED = "deleted"


class SDLCPhase(str, PyEnum):
    REQUIREMENTS = "requirements"
    UIUX = "uiux"
    ARCHITECTURE = "architecture"
    API_BUILDER = "api_builder"
    CODE_GENERATION = "code_generation"
    TESTING = "testing"
    EXPORT = "export"
    COMPLETED = "completed"


class AppPlatform(str, PyEnum):
    WEB = "web"
    MOBILE_IOS = "mobile_ios"
    MOBILE_ANDROID = "mobile_android"
    DESKTOP_WINDOWS = "desktop_windows"
    DESKTOP_MAC = "desktop_mac"
    DESKTOP_LINUX = "desktop_linux"
    ALL = "all"


class AppCategory(str, PyEnum):
    ECOMMERCE = "ecommerce"
    SOCIAL = "social"
    PRODUCTIVITY = "productivity"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    FINANCE = "finance"
    ENTERTAINMENT = "entertainment"
    TRAVEL = "travel"
    FOOD = "food"
    FITNESS = "fitness"
    BUSINESS = "business"
    UTILITY = "utility"
    GAME = "game"
    OTHER = "other"


class ComplexityLevel(str, PyEnum):
    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"


# ───────────────────────────────────────────────
#  Project Model
# ───────────────────────────────────────────────
class Project(Base):
    """
    VengaiCode project — one complete app build session.
    Each project goes through all SDLC phases:
    Requirements → UI/UX → Architecture → API → CodeGen → Testing → Export
    """
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_user_id", "user_id"),
        Index("ix_projects_status", "status"),
        Index("ix_projects_current_phase", "current_phase"),
        Index("ix_projects_created_at", "created_at"),
    )

    # ── Primary Key ──
    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )

    # ── Ownership ──
    user_id: str = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Basic Info ──
    name: str = Column(String(255), nullable=False)
    description: Optional[str] = Column(Text, nullable=True)
    # User's raw idea in plain English
    raw_idea: Optional[str] = Column(Text, nullable=True)

    # ── App Configuration ──
    category: AppCategory = Column(
        Enum(AppCategory),
        default=AppCategory.OTHER,
        nullable=False,
    )
    complexity: ComplexityLevel = Column(
        Enum(ComplexityLevel),
        nullable=True,
    )
    # AI auto-detects complexity from requirements
    platforms: list = Column(JSON, default=list, nullable=False)
    # List of AppPlatform values e.g. ["web", "mobile_ios", "mobile_android"]

    # ── SDLC Progress ──
    status: ProjectStatus = Column(
        Enum(ProjectStatus),
        default=ProjectStatus.DRAFT,
        nullable=False,
        index=True,
    )
    current_phase: SDLCPhase = Column(
        Enum(SDLCPhase),
        default=SDLCPhase.REQUIREMENTS,
        nullable=False,
        index=True,
    )
    progress_percent: float = Column(Float, default=0.0, nullable=False)
    # 0.0 to 100.0

    # ── Phase Completion Tracking ──
    phases_completed: list = Column(JSON, default=list, nullable=False)
    # List of completed phase names
    phase_started_at: Optional[dict] = Column(JSON, default=dict, nullable=False)
    # {"requirements": "2024-01-01T00:00:00", "uiux": "2024-01-01T01:00:00"}
    phase_completed_at: Optional[dict] = Column(JSON, default=dict, nullable=False)
    # Same structure — when each phase was completed

    # ── Chat (available on every phase screen) ──
    chat_messages: list = Column(JSON, default=list, nullable=False)
    # [{"id", "phase", "role": "user"|"assistant", "content", "intent",
    #   "created_at"}, ...] — one continuous thread across all phases.
    # "intent" ("question" | "requirement_change") is set on assistant
    # messages only. A requirement_change message resets requirements_data
    # and phases_completed and sends the user back to Requirements — see
    # api/v1/chat.py.

    # ── AI Understanding ──
    understanding_score: float = Column(Float, default=0.0, nullable=False)
    # 0.0 to 100.0 — how well AI understood user's requirements
    # Build only starts when this reaches 100.0
    ai_conversation_history: list = Column(JSON, default=list, nullable=False)
    # Full conversation history between user and AI
    # [{"role": "ai", "content": "..."}, {"role": "user", "content": "..."}]

    # ── Requirements Phase Data ──
    requirements_data: Optional[dict] = Column(JSON, nullable=True)
    # {
    #   "frd": "...",           — Functional Requirements Document
    #   "srs": "...",           — Software Requirements Specification
    #   "brd": "...",           — Business Requirements Document
    #   "user_approved": true,  — User approved FRD
    #   "approved_at": "..."
    # }

    # ── UI/UX Phase Data ──
    uiux_data: Optional[dict] = Column(JSON, nullable=True)
    # {
    #   "design": {              — AI-generated design system (uiux.py /generate)
    #     "design_style", "color_palette", "typography",
    #     "screens": [...], "components": [...], "navigation_pattern"
    #   },
    #   "user_approved": bool,
    #   "generated_at": "...",
    #   "approved_at": "...",
    #   "uploaded_designs": [     — User-uploaded page mockups (design-to-code)
    #     {
    #       "id", "page_name", "image_url",   — file upload OR camera capture,
    #                                            same Supabase Storage public URL
    #       "uploaded_at",
    #       "generated_html", "generated_css", — AI-extracted, user-editable
    #       "generation_notes",
    #       "code_generated_at", "code_updated_at",
    #       "voice_note_url",                 — raw recording, Supabase Storage
    #       "voice_note_transcript",          — Groq Whisper transcript, folded
    #                                            into the next code-gen prompt
    #       "voice_note_uploaded_at"
    #     }
    #   ]
    # }

    # ── Architecture Phase Data ──
    architecture_data: Optional[dict] = Column(JSON, nullable=True)
    # {
    #   "tech_stack": {...},    — Selected open-source tech stack
    #   "database_schema": {}, — ERD and schema design
    #   "system_diagram": "...",— C4 architecture diagram (Mermaid)
    #   "adrs": [...]           — Architecture Decision Records
    # }

    # ── Structured Stack Selection (distinct from architecture_data's free-text tech_stack) ──
    selected_stack: Optional[dict] = Column(JSON, nullable=True)
    # {
    #   "frontend_language": "javascript", "frontend_framework": "react",
    #   "backend_language": "python", "backend_framework": "fastapi",
    #   "api_style": "rest",
    #   "buildable_now": true,
    #   "validated_at": "..."
    # }
    # Set by POST /stack/select once the combo passes
    # app.ai.stack_matrix.validate_stack(). Authoritative source for
    # app.ai.stack_matrix.get_project_stack() — codegen.py and export.py
    # read it (via that shared helper) instead of re-sniffing
    # architecture_data's free-text tech_stack.frontend, which is
    # legacy/best-effort only.

    # ── API Builder Phase Data ──
    api_data: Optional[dict] = Column(JSON, nullable=True)
    # {
    #   "endpoints": [...],     — All API endpoints
    #   "openapi_spec": {...},  — OpenAPI/Swagger specification
    #   "tested": true          — APIs have been tested
    # }

    # ── Code Generation Phase Data ──
    codegen_data: Optional[dict] = Column(JSON, nullable=True)
    # {
    #   "files_generated": 34,  — Total files generated
    #   "lines_of_code": 2450,  — Total lines of code
    #   "languages_used": [...],— Programming languages used
    #   "frameworks_used": [...],
    #   "complexity_score": 72, — Code complexity score (lower = better)
    #   "security_score": 96,   — Security analysis score
    #   "performance_score": 88,— Performance optimization score
    #   "quality_report": {...} — Full code quality report
    # }

    # ── Testing Phase Data ──
    testing_data: Optional[dict] = Column(JSON, nullable=True)
    # {
    #   "frameworks_used": [...],
    #   "total_tests": 145,
    #   "tests_passed": 143,
    #   "tests_failed": 2,
    #   "coverage_percent": 87.5,
    #   "bugs_found": 5,
    #   "bugs_fixed": 5,
    #   "test_report_url": "..."
    # }

    # ── Export Phase Data ──
    export_data: Optional[dict] = Column(JSON, nullable=True)
    # {
    #   "exported_at": "...",
    #   "zip_file_url": "...",
    #   "exported_items": [...],— List of what user chose to export
    #   "licence_key": "...",   — Master licence key
    #   "how_to_run_url": "...",
    #   "published_to_marketplace": false
    # }

    # ── UML Diagrams ──
    uml_diagrams: Optional[dict] = Column(JSON, nullable=True)
    # {
    #   "use_case": "mermaid_code...",
    #   "class": "mermaid_code...",
    #   "sequence": "mermaid_code...",
    #   "erd": "mermaid_code...",
    #   "component": "mermaid_code...",
    #   "deployment": "mermaid_code..."
    # }

    # ── Time Estimates ──
    estimated_build_time_minutes: Optional[int] = Column(Integer, nullable=True)
    # AI's estimate before starting
    actual_build_time_minutes: Optional[int] = Column(Integer, nullable=True)
    # Actual time taken

    # ── Change Requests ──
    change_requests: list = Column(JSON, default=list, nullable=False)
    # [
    #   {
    #     "id": "...",
    #     "description": "...",
    #     "phase_affected": "requirements",
    #     "status": "applied",
    #     "created_at": "...",
    #     "applied_at": "..."
    #   }
    # ]

    # ── Reference Apps ──
    reference_apps: list = Column(JSON, default=list, nullable=False)
    # Apps user mentioned as references e.g. ["instagram", "amazon"]
    # AI searched and analysed these

    # ── Unique Features ──
    unique_features: list = Column(JSON, default=list, nullable=False)
    # Features that were rare/unique — received Uniqueness Certificate

    # ── Satisfaction ──
    satisfaction_score: Optional[int] = Column(Integer, nullable=True)
    # 1-10 user satisfaction rating after completion
    satisfaction_feedback: Optional[str] = Column(Text, nullable=True)

    # ── Licence & Publishing ──
    licence_key: Optional[str] = Column(String(500), nullable=True)
    # Master licence key for this project
    is_published: bool = Column(Boolean, default=False, nullable=False)
    marketplace_app_id: Optional[str] = Column(String(36), nullable=True)
    # If published to marketplace

    # ── Baby Tiger Stamp Config 🐯 ──
    tiger_stamp_position: str = Column(String(50), default="bottom_right", nullable=False)
    tiger_stamp_size: str = Column(String(20), default="small", nullable=False)
    tiger_stamp_style: str = Column(String(20), default="minimal", nullable=False)
    tiger_stamp_animation: str = Column(String(30), default="subtle_wink", nullable=False)
    tiger_stamp_visibility: str = Column(String(30), default="always_visible", nullable=False)
    # Seller can configure appearance — NOT presence

    # ── Thumbnail ──
    thumbnail_url: Optional[str] = Column(String(500), nullable=True)

    # ── Storage Paths ──
    storage_path: Optional[str] = Column(String(500), nullable=True)
    # Path in Cloudflare R2 where project files are stored

    # ── Metadata ──
    created_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    deleted_at: Optional[datetime] = Column(DateTime(timezone=True), nullable=True)
    # Soft delete

    # ── Relationships ──
    user = relationship("User", back_populates="projects")
    """licences = relationship(
       "Licence",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )"""

    # ── Helper Methods ──
    def get_progress_percent(self) -> float:
        """Calculate progress based on completed phases."""
        phase_weights = {
            SDLCPhase.REQUIREMENTS: 15,
            SDLCPhase.UIUX: 15,
            SDLCPhase.ARCHITECTURE: 10,
            SDLCPhase.API_BUILDER: 10,
            SDLCPhase.CODE_GENERATION: 25,
            SDLCPhase.TESTING: 15,
            SDLCPhase.EXPORT: 10,
        }
        total = sum(
            phase_weights.get(SDLCPhase(phase), 0)
            for phase in self.phases_completed
        )
        return min(100.0, float(total))

    def is_phase_completed(self, phase: SDLCPhase) -> bool:
        return phase.value in self.phases_completed

    def get_next_phase(self) -> Optional[SDLCPhase]:
        """Get the next phase after current."""
        phase_order = [
            SDLCPhase.REQUIREMENTS,
            SDLCPhase.UIUX,
            SDLCPhase.ARCHITECTURE,
            SDLCPhase.API_BUILDER,
            SDLCPhase.CODE_GENERATION,
            SDLCPhase.TESTING,
            SDLCPhase.EXPORT,
        ]
        try:
            current_idx = phase_order.index(self.current_phase)
            if current_idx < len(phase_order) - 1:
                return phase_order[current_idx + 1]
        except ValueError:
            pass
        return None

    def can_proceed_to_next_phase(self) -> bool:
        """Check if current phase is complete enough to proceed."""
        if self.current_phase == SDLCPhase.REQUIREMENTS:
            return (
                self.understanding_score >= 100.0
                and self.requirements_data is not None
                and self.requirements_data.get("user_approved", False)
            )
        return self.is_phase_completed(self.current_phase)

    def __repr__(self) -> str:
        return (
            f"<Project id={self.id[:8]}... name={self.name!r} "
            f"phase={self.current_phase} status={self.status}>"
        )


# ───────────────────────────────────────────────
#  SDLC Phase History Model
# ───────────────────────────────────────────────
class SDLCPhaseHistory(Base):
    """
    Detailed history of every SDLC phase for each project.
    Tracks every time a phase was started, completed, or revisited.
    Enables full phase revisit and change tracking.
    """
    __tablename__ = "sdlc_phase_history"
    __table_args__ = (
        Index("ix_phase_history_project_id", "project_id"),
        Index("ix_phase_history_phase", "phase"),
        Index("ix_phase_history_created_at", "created_at"),
    )

    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    project_id: str = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phase: SDLCPhase = Column(Enum(SDLCPhase), nullable=False)
    action: str = Column(String(50), nullable=False)
    # "started", "completed", "revisited", "reverted", "change_requested"
    phase_data_snapshot: Optional[dict] = Column(JSON, nullable=True)
    # Snapshot of phase data at this point in time
    change_request_id: Optional[str] = Column(String(36), nullable=True)
    # If this history entry was triggered by a change request
    ai_impact_analysis: Optional[dict] = Column(JSON, nullable=True)
    # AI analysis of what this change affects
    # {
    #   "affected_phases": ["uiux", "codegen"],
    #   "impact_description": "...",
    #   "recommendation": "restart_from_uiux"
    # }
    created_at: datetime = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<SDLCPhaseHistory project={self.project_id[:8]}... "
            f"phase={self.phase} action={self.action}>"
        )
