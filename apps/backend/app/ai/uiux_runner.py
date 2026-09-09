# ═══════════════════════════════════════════════════════════════
#  VengaiCode — UI/UX Design Runner
#  ai/uiux_runner.py — UI/UX generation expressed as resumable steps:
#  one AI call for the design system, then one per screen for its HTML+
#  CSS mockup.
#
#  Same generation the API used to do inline; what changed is that
#  services/generation_jobs.py drives the steps in the background and
#  saves after each one. A 4-screen app finished well inside an HTTP
#  timeout, a 20-screen one didn't — and every mockup already paid for
#  was thrown away with the request.
#
#  Unlike codegen, this phase can't plan its whole run up front: how
#  many screens there are is decided BY the first step. steps() reads
#  the design out of the run's saved state, so the step list grows once
#  the design system exists.
# ═══════════════════════════════════════════════════════════════

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from app.ai.orchestrator import AIError, generate_text
from app.ai.uiux_prompts import (
    UIUX_DESIGN_MAX_TOKENS,
    UIUX_MOCKUP_MAX_TOKENS,
    build_screen_to_code_prompt,
    build_uiux_prompt,
    parse_ai_json,
)
from app.models.project import Project
from app.schemas.uiux import UIUXDesign
from app.services.generation_jobs import PhaseRunner, StepCtx

logger = logging.getLogger("vengaicode.uiux")

PHASE = "uiux"


class UIUXError(RuntimeError):
    """A failure with a message meant for the user, not a stack trace."""


def fingerprint(project: Project) -> str:
    """The approved requirements are the whole input to this phase — if
    they change, a half-finished design belongs to a different app."""
    frd = (project.requirements_data or {}).get("frd", {})
    material = json.dumps({"name": project.name, "frd": frd}, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def steps(project: Project, state: dict) -> list[dict]:
    plan = [{"kind": "design", "index": 0, "label": "Design system"}]

    design = state.get("design")
    if not design:
        # The screen list doesn't exist yet — the design step creates it.
        return plan

    for i, screen in enumerate(design.get("screens", [])):
        plan.append(
            {
                "kind": "mockup",
                "index": i,
                "label": f"Mockup: {screen.get('name', 'screen')}",
            }
        )
    return plan


async def run_step(ctx: StepCtx) -> None:
    if ctx.step["kind"] == "design":
        await _generate_design(ctx)
    else:
        await _generate_mockup(ctx)


async def _generate_design(ctx: StepCtx) -> None:
    frd = (ctx.project.requirements_data or {}).get("frd", {})

    try:
        ai_result = await generate_text(
            build_uiux_prompt(ctx.project.name, frd),
            max_tokens=UIUX_DESIGN_MAX_TOKENS,
            user=ctx.user,
            db=ctx.db,
        )
        parsed = parse_ai_json(ai_result["text"])
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI UI/UX response: {e}")
        raise UIUXError(
            "Baby Tiger had trouble designing your app. Please try again! 🐯"
        ) from e

    design = UIUXDesign(**parsed)
    for screen in design.screens:
        screen.id = uuid.uuid4().hex

    ctx.state["design"] = design.model_dump()


async def _generate_mockup(ctx: StepCtx) -> None:
    design = ctx.state.get("design") or {}
    screens = design.get("screens", [])
    index = ctx.step["index"]
    if index >= len(screens):
        return

    screen = screens[index]
    palette = design.get("color_palette", {})

    try:
        screen_result = await generate_text(
            build_screen_to_code_prompt(
                screen, design.get("design_style", ""), palette, design.get("typography", "")
            ),
            max_tokens=UIUX_MOCKUP_MAX_TOKENS,
            user=ctx.user,
            db=ctx.db,
        )
        screen_parsed = parse_ai_json(screen_result["text"])
        screen["generated_html"] = screen_parsed.get("html")
        screen["generated_css"] = screen_parsed.get("css")
        modules = screen_parsed.get("modules")
        screen["modules"] = modules if isinstance(modules, list) else []
    except (AIError, json.JSONDecodeError, KeyError, IndexError) as e:
        # Non-fatal — the design system itself already succeeded. The
        # screen just falls back to a text-only card until the user
        # regenerates or uploads their own mockup for it. Unchanged from
        # when this ran inline; one dud screen must not fail the run
        # (and, now, must not cost the user a resume either).
        logger.warning(f"Auto mockup generation failed for screen '{screen.get('name')}': {e}")

    # Reassign so the service persists the mutation.
    design["screens"] = screens
    ctx.state["design"] = design


async def finalize(project: Project, state: dict) -> None:
    project.uiux_data = {
        "design": state.get("design", {}),
        "user_approved": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


RUNNER = PhaseRunner(
    phase=PHASE,
    fingerprint=fingerprint,
    steps=steps,
    run_step=run_step,
    finalize=finalize,
)
