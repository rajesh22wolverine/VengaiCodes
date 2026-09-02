# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Figma REST API Client
#  core/figma_client.py — Thin httpx wrapper around Figma's free REST
#  API (personal access token auth, no OAuth app / paid plan needed).
#  Mirrors core/storage.py's approach: raw httpx calls, no SDK.
# ═══════════════════════════════════════════════════════════════

import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

import httpx

FIGMA_API_BASE = "https://api.figma.com/v1"


class FigmaError(Exception):
    """Raised when a Figma API call fails or a token/URL is invalid."""

    pass


def parse_figma_url(url: str) -> tuple[str, Optional[str]]:
    """
    Extracts (file_key, node_id) from a Figma file/frame URL.

    file_key comes from the /file/{key}/... or /design/{key}/... path
    segment. node_id comes from the ?node-id=123-456 query param (only
    present when the user copied a *specific frame's* link via
    "Copy link to selection") — Figma's UI uses dashes there, but the
    REST API expects a colon, so it's normalized before returning.
    """
    parsed = urlparse(url)
    match = re.search(r"/(?:file|design|proto)/([a-zA-Z0-9]+)", parsed.path)
    if not match:
        raise FigmaError(
            "That doesn't look like a Figma link. Open the file in Figma, "
            "right-click a frame, and choose 'Copy link to selection'."
        )
    file_key = match.group(1)

    node_id = None
    raw_node_id = parse_qs(parsed.query).get("node-id", [None])[0]
    if raw_node_id:
        node_id = raw_node_id.replace("-", ":")

    return file_key, node_id


async def get_figma_user(token: str) -> dict:
    """Validates a token via GET /v1/me and returns {id, email, handle}."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{FIGMA_API_BASE}/me", headers={"X-Figma-Token": token}
        )
    if response.status_code == 403:
        raise FigmaError("That Figma token was rejected — check it and try again.")
    if response.status_code != 200:
        raise FigmaError(f"Figma couldn't validate that token ({response.status_code}).")
    return response.json()


async def export_frame_png(token: str, file_key: str, node_id: str) -> str:
    """
    Exports a single frame/node as a PNG via GET /v1/images and returns
    the temporary S3 URL Figma generates for it.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{FIGMA_API_BASE}/images/{file_key}",
            params={"ids": node_id, "format": "png", "scale": "2"},
            headers={"X-Figma-Token": token},
        )
    if response.status_code == 403:
        raise FigmaError("That Figma token doesn't have access to this file.")
    if response.status_code != 200:
        raise FigmaError(f"Figma couldn't export that frame ({response.status_code}).")

    data = response.json()
    if data.get("err"):
        raise FigmaError(f"Figma couldn't export that frame: {data['err']}")

    image_url = (data.get("images") or {}).get(node_id)
    if not image_url:
        raise FigmaError(
            "Figma didn't return an image for that frame — check the link "
            "and that you have access to the file."
        )
    return image_url
