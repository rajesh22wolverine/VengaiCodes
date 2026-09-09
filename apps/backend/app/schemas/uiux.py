# ═══════════════════════════════════════════════════════════════
#  VengaiCode — UI/UX Design Schemas
#  schemas/uiux.py — The shape of a generated design system.
#
#  Lives here rather than in api/v1/uiux.py because the design is now
#  produced by a background job (ai/uiux_runner.py) as well as read by
#  the route — and the runner can't import the route module without a
#  circular import.
# ═══════════════════════════════════════════════════════════════

from typing import Optional

from pydantic import BaseModel


class ScreenDefinition(BaseModel):
    id: str = ""
    name: str
    purpose: str
    key_elements: list[str]
    generated_html: Optional[str] = None
    generated_css: Optional[str] = None
    modules: list[str] = []


class ColorPalette(BaseModel):
    primary: str
    secondary: str
    accent: str
    background: str
    text: str


class UIUXDesign(BaseModel):
    design_style: str
    color_palette: ColorPalette
    typography: str
    screens: list[ScreenDefinition]
    components: list[str]
    navigation_pattern: str
