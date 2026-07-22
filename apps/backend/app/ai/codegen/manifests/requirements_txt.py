# ═══════════════════════════════════════════════════════════════
#  VengaiCode — requirements.txt Template Builder
#  ai/codegen/manifests/requirements_txt.py — Deterministic pinned-
#  dependency list for Python backend adapters (fastapi, flask, django).
# ═══════════════════════════════════════════════════════════════


def build_requirements_txt(packages: list[str]) -> str:
    return "\n".join(packages) + "\n"
