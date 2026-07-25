# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Secret Encryption
#  core/crypto.py — Symmetric encryption for secrets stored at rest
#  (BYO AI model API keys). Separate from security.py's RSA sign/
#  verify subsystem, which is for licences/stamps, not secret storage.
# ═══════════════════════════════════════════════════════════════

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_fernet_cache: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """
    Load (and cache) a Fernet instance derived from settings.ENCRYPTION_KEY.
    Fernet requires a 32-byte urlsafe-base64 key — ENCRYPTION_KEY is an
    arbitrary configured string, so it's hashed down to 32 bytes first.
    """
    global _fernet_cache
    if _fernet_cache is None:
        digest = hashlib.sha256(settings.ENCRYPTION_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
        _fernet_cache = Fernet(key)
    return _fernet_cache


def encrypt_secret(plain: str) -> str:
    """Encrypt a plaintext secret (e.g. a user's own AI provider API key)."""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a secret previously encrypted with encrypt_secret()."""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("Stored secret could not be decrypted — ENCRYPTION_KEY may have changed.")
