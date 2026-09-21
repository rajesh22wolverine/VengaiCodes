# ═══════════════════════════════════════════════════════════════
#  VengaiCode — "Reverse App" API Routes
#  api/v1/reverse_engineer.py — Turns an EXISTING app (a URL, one or
#  more screenshots, or a plain description) into a synthesized raw_idea
#  string, using the exact same shape CreateTab's free-text box already
#  produces. Nothing downstream needs to change: the frontend feeds the
#  result straight into the existing POST /projects + wizard flow, so
#  this endpoint's only real job is "existing app -> good raw_idea text".
#
#  Three source modes, each producing real "material" fed to one final
#  synthesis AI call:
#    - url: fetches the real page (httpx) and strips it to visible text
#      via the stdlib html.parser — no new dependency (BeautifulSoup)
#      for what's ultimately just a rough sketch handed to the AI, not a
#      structured scrape.
#    - screenshots: reuses orchestrator.generate_vision() (the same
#      Groq vision call already used for the UI/UX phase's design-to-
#      code feature) once per image, asking for a real description of
#      what each screen shows and does.
#    - description: passed straight through.
#
#  SECURITY: source_type="url" fetches a user-supplied URL from this
#  backend's own network — a real SSRF surface (OWASP-relevant) if left
#  unguarded. _validate_public_url() resolves the hostname and rejects
#  private/loopback/link-local/reserved/multicast IP ranges before any
#  request is made, redirects are not followed (a redirect target gets
#  the same "fetch it yourself and paste the final URL" treatment rather
#  than being silently chased into an internal address), and the
#  response is capped before parsing.
# ═══════════════════════════════════════════════════════════════

import base64
import html.parser
import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIError, generate_text, generate_vision
from app.api.v1.auth import get_current_active_user
from app.api.v1.requirements import parse_ai_json
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger("vengaicode.reverse_engineer")
router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_SCREENSHOTS = 5
MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024
MAX_URL_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_URL_TEXT_CHARS = 4000
MAX_MATERIAL_CHARS_IN_PROMPT = 6000


# ─── Schemas ───
class ReverseAnalyzeResponse(BaseModel):
    success: bool = True
    raw_idea: str
    suggested_name: str
    source_summary: str


# ─── URL mode ───
class _VisibleTextExtractor(html.parser.HTMLParser):
    """Strips an HTML document down to its <title> plus visible body
    text. Stdlib-only — this only needs to feed a rough sketch of the
    page to the AI, not a structured DOM, so pulling in BeautifulSoup
    for it would be a dependency this codebase doesn't otherwise need."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title":
            self._in_title = True
        if tag in ("script", "style", "noscript", "svg", "head"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in ("script", "style", "noscript", "svg", "head") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only http:// and https:// URLs are supported.")
    if not parsed.hostname:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That doesn't look like a valid URL.")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not resolve that URL's hostname.")

    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "That URL points at a private or internal address, which isn't allowed.",
            )


async def _analyze_url(url: str) -> str:
    _validate_public_url(url)

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0 (compatible; VengaiCodeBot/1.0; +https://vengaicode.com)"},
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 300:
                    if response.status_code < 400:
                        raise HTTPException(
                            status.HTTP_400_BAD_REQUEST,
                            "That URL redirects elsewhere — try pasting the final destination URL directly.",
                        )
                    raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"That URL returned HTTP {response.status_code}.")

                content_type = response.headers.get("content-type", "")
                if "html" not in content_type:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "That URL doesn't look like a web page (expected HTML).")

                chunks = []
                total = 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= MAX_URL_RESPONSE_BYTES:
                        break
                body = b"".join(chunks).decode("utf-8", errors="replace")
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Couldn't fetch that URL: {e}")

    parser = _VisibleTextExtractor()
    parser.feed(body)
    visible_text = " ".join(parser.text_parts)[:MAX_URL_TEXT_CHARS]
    title = parser.title.strip()

    if not visible_text and not title:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Couldn't find any readable content on that page.")

    return f"Page title: {title or '(none)'}\n\nVisible page text:\n{visible_text}"


# ─── Screenshots mode ───
async def _analyze_screenshots(files: list[UploadFile]) -> str:
    if len(files) > MAX_SCREENSHOTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Please upload at most {MAX_SCREENSHOTS} screenshots.")

    descriptions = []
    for index, file in enumerate(files):
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"'{file.filename}' isn't a supported image type (PNG, JPEG, or WebP only).",
            )
        content = await file.read()
        if len(content) > MAX_SCREENSHOT_BYTES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{file.filename}' is too large (8 MB max).")

        image_b64 = base64.b64encode(content).decode("ascii")
        try:
            result = await generate_vision(
                "Describe this app screen in concrete detail: what screen/page is this, what "
                "real UI elements and content does it show, and what capability or user action "
                "does it represent? Be specific about what you actually see, not generic.",
                image_b64,
                file.content_type,
            )
        except AIError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

        descriptions.append(f"Screenshot {index + 1} ({file.filename}): {result['text']}")

    return "\n\n".join(descriptions)


# ─── Synthesis ───
_SYNTHESIS_PROMPT = """You are Baby Tiger \U0001f42f, VengaiCode's AI assistant. A user wants to build an app inspired by an EXISTING app/website they've pointed you at. Below is real material gathered about that existing app — read it and write a description of an app AS IF the user were describing their own original app idea in their own words (the way they'd type it into an idea box), suitable for VengaiCode's own requirements-gathering wizard to ask follow-up questions about.

Source: {source_kind}

Gathered material:
{material}

Requirements:
- Ground every claim in the real material above — do not invent features or details it doesn't support.
- Do not mention that this was reverse-engineered from another app, a screenshot, or a URL — phrase it as a first-person app idea.
- "raw_idea" should be a detailed paragraph (4-8 sentences): what the app does, who it's for, its core features and screens, and what makes it distinctive.
- "suggested_name" is a short, real app name (2-4 words, no punctuation/quotes).

Respond with ONLY this JSON object, no markdown, no extra text:
{{"suggested_name": "...", "raw_idea": "..."}}"""


@router.post(
    "/analyze",
    response_model=ReverseAnalyzeResponse,
    summary="Analyze an existing app/website and synthesize a VengaiCode project idea from it",
)
async def analyze(
    source_type: str = Form(...),
    url: str | None = Form(None),
    description: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if source_type == "url":
        if not url or not url.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please provide a URL.")
        material = await _analyze_url(url.strip())
        source_kind = f"a website ({url.strip()})"
    elif source_type == "screenshots":
        if not files:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please upload at least one screenshot.")
        material = await _analyze_screenshots(files)
        source_kind = "screenshots of an existing app"
    elif source_type == "description":
        if not description or not description.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please describe the app you want to clone.")
        material = description.strip()
        source_kind = "a text description of an existing app, written by the user"
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_type must be 'url', 'screenshots', or 'description'.")

    prompt = _SYNTHESIS_PROMPT.format(source_kind=source_kind, material=material[:MAX_MATERIAL_CHARS_IN_PROMPT])

    try:
        ai_result = await generate_text(prompt, user=user, db=db)
    except AIError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    try:
        parsed = parse_ai_json(ai_result["text"])
        raw_idea = str(parsed["raw_idea"]).strip()
        suggested_name = str(parsed["suggested_name"]).strip()
    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"Failed to parse reverse-engineer synthesis response: {e}")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Baby Tiger had trouble turning that into an app idea. Please try again! \U0001f42f",
        )

    if not raw_idea:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Baby Tiger couldn't come up with an idea from that. Please try again!")

    return ReverseAnalyzeResponse(
        raw_idea=raw_idea,
        suggested_name=suggested_name or "My App",
        source_summary=material[:300],
    )
