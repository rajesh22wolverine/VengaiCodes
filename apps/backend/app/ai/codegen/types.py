# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Codegen Adapter Types
#  ai/codegen/types.py — The two composable axes code generation is
#  built from: a FrontendAdapter (one per UI framework) and a
#  BackendAdapter (one per backend framework). Any coherent
#  (frontend, backend) pairing from stack_matrix.py combines
#  mechanically — no per-pairing prompt template needed — because each
#  adapter only ever knows about its own framework, never its pair's.
#
#  O3DE is NOT a BackendAdapter pairing (it has no separate backend —
#  stack_matrix.py's "none" sentinel) and is handled by
#  app/ai/codegen/o3de.py instead, kept outside this registry.
# ═══════════════════════════════════════════════════════════════

from dataclasses import dataclass
from typing import Awaitable, Callable

from app.ai.codegen_shared import GeneratedFile

# (file, validation_issue) — issue is None when the file looked OK.
FileResult = tuple[GeneratedFile, str | None]


@dataclass
class ModelCtx:
    project_name: str
    table: dict
    requirements_text: str
    language: str


@dataclass
class RoutesCtx:
    project_name: str
    endpoints: list[dict]
    tables: list[dict]
    requirements_text: str
    api_style: str
    language: str


@dataclass
class ScreenCtx:
    project_name: str
    screen: dict
    endpoints: list[dict]
    requirements_text: str
    native_capabilities: list[str]
    language: str


@dataclass
class WiringCtx:
    """Everything a wiring/manifest builder needs — already-generated
    files plus the project name and the endpoint list, nothing else.
    Deliberately excludes requirements/screens *content*: manifest and
    entry-point files are boilerplate glue, not business logic, so they
    never need the app's domain text, only the shape of what was
    already generated. `endpoints` and `tables` are the two exceptions —
    frameworks that split routing/schema from view/model logic (Django's
    urls.py vs views.py; Rails' migrations vs ActiveRecord models, which
    don't declare columns themselves) need the same structured data used
    to generate the routes/model files, to deterministically wire URL
    patterns to exact view names, or declare exact column types, without
    re-deriving them from AI-authored file content."""
    project_name: str
    model_files: list[GeneratedFile]
    routes_files: list[GeneratedFile]
    screen_files: list[GeneratedFile]
    endpoints: list[dict]
    tables: list[dict]


@dataclass(frozen=True)
class FrontendAdapter:
    key: str
    label: str
    # Which stack_matrix.py FRONTEND_FRAMEWORKS[key]["languages"] entries
    # this adapter actually implements — used by
    # stack_matrix._compute_buildable_now() so a framework that supports
    # e.g. both JS and TS isn't marked buildable for a language variant
    # the adapter never emits.
    supported_languages: tuple[str, ...]
    generate_screen: Callable[[ScreenCtx], Awaitable[FileResult]]
    # Deterministic (no AI call) — populated from Phase 1B onward. None
    # means this adapter still relies on codegen.py's legacy combined
    # wiring AI call for its glue files.
    manifest_files: "Callable[[WiringCtx], list[GeneratedFile]] | None" = None
    entry_point_files: "Callable[[WiringCtx], list[GeneratedFile]] | None" = None
    setup_commands: "Callable[[str], list[str]] | None" = None


@dataclass(frozen=True)
class BackendAdapter:
    key: str
    label: str
    supported_languages: tuple[str, ...]
    # Derived from this adapter's own routes-builder dict (see any
    # backend/*.py), never hand-maintained separately — keeps
    # stack_matrix.BACKEND_FRAMEWORKS's claim and this adapter's actual
    # capability from silently drifting apart.
    supported_api_styles: tuple[str, ...]
    generate_model: Callable[[ModelCtx], Awaitable[FileResult]]
    # Returns a list, not a single file — gRPC needs both a .proto file
    # and a service-implementation stub from one generation step.
    generate_routes: Callable[[RoutesCtx], Awaitable[list[FileResult]]]
    manifest_files: "Callable[[WiringCtx], list[GeneratedFile]] | None" = None
    entry_point_files: "Callable[[WiringCtx], list[GeneratedFile]] | None" = None
    setup_commands: "Callable[[str], list[str]] | None" = None
