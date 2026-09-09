# ═══════════════════════════════════════════════════════════════
#  VengaiCode — UI/UX Prompts
#  ai/uiux_prompts.py — The prompts the UI/UX phase sends, and the
#  JSON parsing of what comes back.
#
#  Moved out of api/v1/uiux.py unchanged: design generation now runs
#  as a background job (ai/uiux_runner.py), and the runner can't import
#  the route module without a circular import.
# ═══════════════════════════════════════════════════════════════

import json
from typing import Optional


# ─── Prompt builder ───
def build_uiux_prompt(project_name: str, requirements: dict) -> str:
    features = ", ".join(requirements.get("key_features", []))
    platforms = ", ".join(requirements.get("platforms", []))

    return f"""You are Baby Tiger 🐯, VengaiCode's AI design assistant. Based on this app's approved requirements, design a UI/UX system.

App: {project_name}
Overview: {requirements.get('overview', '')}
Key features: {features}
Platforms: {platforms}
Target users: {requirements.get('target_users', '')}

Generate a JSON object with EXACTLY these fields (no markdown, no extra text, just valid JSON):
{{
  "design_style": "1 sentence describing the visual style (e.g. 'clean and minimal with rounded corners, energetic accent colors')",
  "color_palette": {{
    "primary": "#hexcode",
    "secondary": "#hexcode",
    "accent": "#hexcode",
    "background": "#hexcode",
    "text": "#hexcode"
  }},
  "typography": "1 sentence on font choice and why it fits (e.g. 'Inter for a modern, friendly, highly readable feel')",
  "screens": [
    {{"name": "Screen Name", "purpose": "1 sentence what this screen does", "key_elements": ["element1", "element2", "element3"]}}
  ],
  "components": ["reusable component 1", "reusable component 2", "reusable component 3"],
  "navigation_pattern": "1 sentence describing how users move between screens (e.g. 'bottom tab bar with 4 main sections')"
}}

Generate 4-6 screens covering the core user journey. Pick colors that suit the app's purpose and target users. Choose real, valid hex codes.

Respond with ONLY the JSON object, nothing else."""


def build_design_to_code_prompt(page_name: str, voice_instructions: Optional[str] = None) -> str:
    voice_section = ""
    if voice_instructions:
        voice_section = f"""

The user also recorded a voice note with additional instructions — \
follow these along with what you see in the image:
"{voice_instructions}\""""

    return f"""You are Baby Tiger 🐯, VengaiCode's AI design-to-code assistant. \
Look at the attached page design image (for a page called "{page_name}") and \
recreate it as HTML + CSS as faithfully as you can — layout, spacing, colors, \
typography, and visible text/labels.{voice_section}

Rules:
- Use plain semantic HTML5 (no framework, no Tailwind classes) with a single \
  matching CSS stylesheet — this needs to be readable and directly editable
  by the user afterward, not a build pipeline.
- Match colors (as hex), approximate spacing/sizing, and text content as
  closely as you can infer from the image.
- Use placeholder text/images only where the design shows content you can't
  read clearly.
- Wrap each distinct structural section you identify in its own top-level
  container element carrying a `data-veng-module="<name>"` attribute, where
  `<name>` exactly matches one entry of the "modules" array you return below
  (e.g. `<header data-veng-module="Header nav">...</header>`). This is what
  lets the editor move/reorder whole sections later — every module you
  report must correspond to exactly one real, addressable element.

Respond with ONLY a JSON object, no markdown, no extra text:
{{
  "html": "<the full HTML markup for this page's body content, as a string>",
  "css": "<the full CSS, as a string>",
  "notes": "1 sentence on anything you weren't confident about",
  "modules": ["3 to 6 short names for the distinct structural sections/components you see, e.g. 'Header nav', 'Hero banner', 'Pricing cards', 'Footer'"]
}}"""


def build_screen_to_code_prompt(
    screen: dict, design_style: str, color_palette: dict, typography: str
) -> str:
    key_elements = ", ".join(screen.get("key_elements", []))
    palette_text = ", ".join(f"{k}: {v}" for k, v in color_palette.items())

    return f"""You are Baby Tiger 🐯, VengaiCode's AI design assistant. Design a single \
page mockup, as HTML + CSS, for the "{screen.get('name', 'Screen')}" screen of this app.

Screen purpose: {screen.get('purpose', '')}
Key elements this screen needs: {key_elements}

Match the app's design system:
- Style: {design_style}
- Color palette: {palette_text}
- Typography: {typography}

Rules:
- Use plain semantic HTML5 (no framework, no Tailwind classes) with a single \
  matching CSS stylesheet — this needs to be readable and directly editable
  by the user afterward, not a build pipeline.
- Use real hex colors from the palette above, and reflect the stated style
  and typography choice.
- Use realistic placeholder text/labels appropriate to the screen's purpose
  and key elements — no lorem ipsum.
- Wrap each distinct structural section you create in its own top-level
  container element carrying a `data-veng-module="<name>"` attribute, where
  `<name>` exactly matches one entry of the "modules" array you return below
  (e.g. `<header data-veng-module="Header nav">...</header>`). This is what
  lets the editor move/reorder whole sections later — every module you
  report must correspond to exactly one real, addressable element.

Respond with ONLY a JSON object, no markdown, no extra text:
{{
  "html": "<the full HTML markup for this page's body content, as a string>",
  "css": "<the full CSS, as a string>",
  "notes": "1 sentence on anything you weren't confident about",
  "modules": ["3 to 6 short names for the distinct structural sections you created, e.g. 'Header nav', 'Hero banner', 'Pricing cards', 'Footer'"]
}}"""


# Both UI/UX calls once inherited a 4096-token default, which was far too
# small for the mockup call and left it truncated mid-markup: the reply
# came back HTTP 200 but json.loads() failed with "Unterminated string
# starting at: line 2 column 11" — column 11 of line 2 is the opening
# quote of the "html" value, i.e. it was cut off before the markup even
# got going. The screen then silently fell back to a text-only card.
#
# Sizing these by hand (6000 / 12000) fixed that but only moved the wall
# further out: a mockup returns a whole HTML page AND its stylesheet, both
# embedded as JSON strings, so every quote and newline in the markup is
# escaped and counted, and a rich enough screen still hit the ceiling.
#
# None removes the wall. VengaiCode sets no ceiling of its own on either
# call; the provider's model maximum is the limit, and a truncated mockup
# now means the model genuinely ran out of room rather than that we
# guessed a number too low. See settings.AI_MAX_TOKENS.
UIUX_DESIGN_MAX_TOKENS: int | None = None   # compact JSON: palette, typography, screens
UIUX_MOCKUP_MAX_TOKENS: int | None = None   # a full HTML page + CSS, JSON-escaped


def parse_ai_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)
