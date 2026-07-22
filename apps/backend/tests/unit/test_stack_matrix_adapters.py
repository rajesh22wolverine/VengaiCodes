# ═══════════════════════════════════════════════════════════════
#  Guards against stack_matrix.py's BACKEND_FRAMEWORKS and the codegen
#  adapter registry silently drifting apart.
#
#  The real invariant worth enforcing is one-directional: an adapter
#  must never claim to support an API style the matrix doesn't declare
#  for that framework (that would let stack_matrix._compute_buildable_now()
#  mark a combo buildable that isn't actually coherent). The reverse —
#  the matrix declaring a style (e.g. GraphQL) that no adapter has
#  implemented yet — is expected and fine: it just means that combo
#  isn't buildable yet, which find_nearest()'s fallback already handles
#  honestly. So this is a subset check, not an equality check.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.backend import BACKEND_ADAPTERS
from app.ai.codegen.frontend import FRONTEND_ADAPTERS
from app.ai.stack_matrix import BACKEND_FRAMEWORKS, FRONTEND_FRAMEWORKS


def test_backend_adapter_api_styles_never_exceed_the_matrix():
    for key, adapter in BACKEND_ADAPTERS.items():
        declared = set(a for a in BACKEND_FRAMEWORKS[key]["api_styles"] if a != "none")
        claimed = set(adapter.supported_api_styles)
        assert claimed <= declared, (
            f"{key} adapter claims api styles {claimed - declared} that "
            f"stack_matrix.BACKEND_FRAMEWORKS['{key}'] doesn't declare"
        )


def test_backend_adapter_languages_never_exceed_the_matrix():
    for key, adapter in BACKEND_ADAPTERS.items():
        declared = set(BACKEND_FRAMEWORKS[key]["languages"])
        claimed = set(adapter.supported_languages)
        assert claimed <= declared, (
            f"{key} adapter claims languages {claimed - declared} that "
            f"stack_matrix.BACKEND_FRAMEWORKS['{key}'] doesn't declare"
        )


def test_frontend_adapter_languages_never_exceed_the_matrix():
    for key, adapter in FRONTEND_ADAPTERS.items():
        declared = set(FRONTEND_FRAMEWORKS[key]["languages"])
        claimed = set(adapter.supported_languages)
        assert claimed <= declared, (
            f"{key} adapter claims languages {claimed - declared} that "
            f"stack_matrix.FRONTEND_FRAMEWORKS['{key}'] doesn't declare"
        )


def test_every_registered_adapter_key_exists_in_the_matrix():
    """Catches a typo'd adapter key that would never actually be reachable
    through stack_matrix._compute_buildable_now()."""
    for key in BACKEND_ADAPTERS:
        assert key in BACKEND_FRAMEWORKS, f"backend adapter '{key}' has no matching stack_matrix.BACKEND_FRAMEWORKS entry"
    for key in FRONTEND_ADAPTERS:
        assert key in FRONTEND_FRAMEWORKS, f"frontend adapter '{key}' has no matching stack_matrix.FRONTEND_FRAMEWORKS entry"
