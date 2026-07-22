# ═══════════════════════════════════════════════════════════════
#  VengaiCode — README_SETUP.md Builder
#  ai/codegen/readme.py — Assembles each adapter's setup_commands()
#  into one README_SETUP.md. Deterministic, no AI call — the commands
#  themselves are the whole point (they must be literally correct).
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen_shared import GeneratedFile


def build_readme_setup(
    project_name: str,
    backend_commands: list[str] | None,
    frontend_commands: list[str] | None,
    extra_notes: list[str] | None = None,
) -> GeneratedFile:
    lines = [f"# {project_name} — Setup", ""]

    if backend_commands:
        lines += ["## Backend", "", "```bash", *backend_commands, "```", ""]
    if frontend_commands:
        lines += ["## Frontend", "", "```bash", *frontend_commands, "```", ""]
    if extra_notes:
        lines += ["## Notes", ""] + [f"- {note}" for note in extra_notes] + [""]

    return GeneratedFile(
        path="README_SETUP.md",
        language="markdown",
        content="\n".join(lines),
        description="Exact setup/run commands for this project",
    )
