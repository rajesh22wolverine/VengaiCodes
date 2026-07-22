# ═══════════════════════════════════════════════════════════════
#  VengaiCode — O3DE Special Case
#  ai/codegen/o3de.py — O3DE pairs with stack_matrix.py's "none" backend
#  sentinel (no separate backend at all), so it never fit the
#  FrontendAdapter/BackendAdapter pairing shape used by every other
#  stack. Kept as its own small, self-contained module instead of
#  forcing a BackendAdapter("none") that would just be a pile of no-ops.
#  Logic moved verbatim from the old codegen.py stack_target branches —
#  no behavior change.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.types import FileResult, ScreenCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, generate_text_validated


async def generate_screen(ctx: ScreenCtx) -> FileResult:
    screen_name = ctx.screen.get("name", "Screen")
    component_name = _pascal(screen_name)

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete O3DE scene/script stub implementing the "{screen_name}" scene of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Scene purpose: {ctx.screen.get('purpose', '')}

Implement the real behavior described above for this scene — no placeholders.
Return ONLY the raw file content. No markdown fences, no explanation, no JSON."""
    content, issue = await generate_text_validated(prompt, "javascript", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"frontend/src/screens/{component_name}.jsx",
        language="javascript",
        content=content,
        description=f"Screen implementing {screen_name}",
    ), issue


def build_wiring_prompt(project_name: str, screen_paths: str) -> str:
    return f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Generate the wiring/config files for an O3DE project.

App: {project_name}
Scene files already generated: {screen_paths}

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "summary": "2-3 sentences on the project structure",
  "files": [
    {{"path": "...", "language": "...", "content": "...", "description": "..."}}
  ]
}}

Include the O3DE project/workspace config files and a README_SETUP.md with exact setup commands.
Return ONLY valid JSON, nothing else."""
