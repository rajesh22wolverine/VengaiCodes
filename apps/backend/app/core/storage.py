# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Object Storage (Supabase Storage)
#  core/storage.py — Upload/fetch user files via Supabase's
#  S3-compatible, open-source Storage API.
#
#  Uses raw REST calls via httpx (matches the pattern already used
#  for the GitHub API in packaging.py) instead of pulling in the
#  `supabase` SDK as a new dependency.
#
#  REQUIRES the bucket named settings.SUPABASE_DESIGN_UPLOADS_BUCKET
#  to already exist in your Supabase project and be public — this
#  module does not create it. See config.py for setup notes.
# ═══════════════════════════════════════════════════════════════

import logging
import uuid

import httpx

from app.config import settings

logger = logging.getLogger("vengaicode.storage")


class StorageError(Exception):
    """Raised when Supabase Storage is not configured or a request fails."""

    pass


def _require_configured():
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise StorageError(
            "Supabase Storage is not configured (missing SUPABASE_URL / "
            "SUPABASE_SERVICE_KEY)."
        )


async def upload_design_image(
    project_id: str, filename: str, content: bytes, content_type: str
) -> str:
    """
    Uploads a design image to the design-uploads bucket and returns its
    public URL. Raises StorageError on misconfiguration or upload failure.
    """
    _require_configured()

    bucket = settings.SUPABASE_DESIGN_UPLOADS_BUCKET
    safe_name = filename.replace("/", "_").replace("\\", "_")
    object_path = f"{project_id}/{uuid.uuid4().hex}_{safe_name}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.SUPABASE_URL}/storage/v1/object/{bucket}/{object_path}",
            headers={
                "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            content=content,
        )

    if response.status_code not in (200, 201):
        logger.error(f"Supabase Storage upload failed: {response.status_code} {response.text}")
        raise StorageError(f"Upload failed ({response.status_code}). Is the bucket public?")

    return f"{settings.SUPABASE_URL}/storage/v1/object/public/{bucket}/{object_path}"


async def fetch_bytes(url: str) -> bytes:
    """Downloads bytes from a (typically Supabase public) URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
    response.raise_for_status()
    return response.content
