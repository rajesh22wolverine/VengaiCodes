# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Knowledge API Routes
#  api/v1/knowledge.py — Read-only view of what VengaiCode knows about
#  languages, frameworks and SDLC phases (app/ai/knowledge/): the same
#  rules its validators enforce and its AI prompts carry.
#
#    GET /knowledge                      everything
#    GET /knowledge/languages/{key}      one language
#    GET /knowledge/frameworks/{key}     one framework
# ═══════════════════════════════════════════════════════════════

from fastapi import APIRouter, HTTPException, status

from app.ai import knowledge

router = APIRouter()


@router.get("", summary="Languages, frameworks and SDLC phases VengaiCode knows")
async def get_catalog():
    return {"success": True, **knowledge.catalog()}


@router.get("/languages/{key}", summary="One language's rules")
async def get_language(key: str):
    spec = knowledge.language(key)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f'No language "{key}".'
        )
    return {
        "success": True,
        "language": next(
            item for item in knowledge.catalog()["languages"] if item["key"] == spec.key
        ),
    }


@router.get("/frameworks/{key}", summary="One framework's rules")
async def get_framework(key: str):
    spec = knowledge.framework(key)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f'No framework "{key}".'
        )
    return {
        "success": True,
        "framework": next(
            item
            for item in knowledge.catalog()["frameworks"]
            if item["key"] == spec.key
        ),
    }
