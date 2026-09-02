# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Figma Schemas
#  schemas/figma.py — Request/response shapes for connecting a Figma
#  account and importing a frame as a page design.
# ═══════════════════════════════════════════════════════════════

from typing import Optional

from pydantic import BaseModel, Field


class FigmaConnectRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=500)
    # Plaintext in the request only — encrypted before it touches the DB.


class FigmaConnectionResponse(BaseModel):
    success: bool = True
    connected: bool
    figma_handle: Optional[str] = None
    # Never includes the raw/decrypted token.


class DisconnectFigmaResponse(BaseModel):
    success: bool = True
    message: str = "Figma account disconnected."


class ImportFigmaRequest(BaseModel):
    figma_url: str = Field(..., min_length=1)
    page_name: str = Field(..., min_length=1, max_length=200)
