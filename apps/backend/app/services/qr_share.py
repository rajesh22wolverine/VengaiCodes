# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Share via QR (the logic, no HTTP)
#  services/qr_share.py — Three ways to hand a project to someone with a
#  QR code, because no single one fits every case. A real project is far
#  bigger than a QR code: one symbol holds at most 2,953 bytes, and a
#  small generated app compresses to ~15 KB (measured, 2026-09-25). So:
#
#    1. Download link — the QR holds a short, expiring URL to the ZIP
#       (api/v1/share.py). Any size, any camera; needs the server.
#    2. Blueprint — ONE QR holding the design itself (name, stack, tables,
#       endpoints), compressed. Offline. The app is rebuilt from it by the
#       No-AI generator; AI-written code and documents don't travel.
#    3. QR sequence — the whole bundle (code + documents) split across
#       many codes shown one after another, read by the VengaiCode mobile
#       app. Offline and complete, but it takes a stream of codes.
#
#  Text formats (both stay inside the QR "alphanumeric" character set —
#  0-9 A-Z space $ % * + - . / : — which packs 5.5 bits per character
#  and survives every scanner library unchanged, unlike raw binary):
#    blueprint  VGC1:<base45(raw-deflate(JSON))>
#    frame      VGS1:<SID>:<index>:<count>:<base45(chunk)>
#  base45 is RFC 9285 (the encoding EU COVID certificates used in QR codes
#  for the same reason). SID is the CRC32 of the whole compressed payload
#  in hex: together with <count> it keeps frames of two transfers apart
#  (the same project in a different frame size has the same SID but a
#  different count), and it checks the reassembled result.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import base64
import io
import json
import zlib
from dataclasses import dataclass, field
from typing import Any

import segno

BASE45_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
_BASE45_INDEX = {ch: i for i, ch in enumerate(BASE45_ALPHABET)}

BLUEPRINT_PREFIX = "VGC1:"
SEQUENCE_PREFIX = "VGS1"

# Past this QR version (~117x117 modules) a code gets hard to read from a
# phone screen or a small print; the UI says so rather than refusing.
DENSE_QR_VERSION = 25

MIN_FRAME_BYTES = 200
MAX_FRAME_BYTES = 1200
DEFAULT_FRAME_BYTES = 500
MAX_SEQUENCE_FRAMES = 600

# Decompression limits — a hostile code can't make the server (or the
# phone) inflate a few KB into gigabytes.
MAX_BLUEPRINT_JSON_BYTES = 1_000_000
MAX_BLUEPRINT_TABLES = 200
MAX_BLUEPRINT_ENDPOINTS = 500


class QrShareError(ValueError):
    """A problem the user can act on — the message is shown as-is."""


# ───────────────────────────────────────────────
#  base45 (RFC 9285)
# ───────────────────────────────────────────────
def base45_encode(data: bytes) -> str:
    out = []
    for i in range(0, len(data) - 1, 2):
        n = data[i] * 256 + data[i + 1]
        n, c = divmod(n, 45)
        e, d = divmod(n, 45)
        out += [BASE45_ALPHABET[c], BASE45_ALPHABET[d], BASE45_ALPHABET[e]]
    if len(data) % 2:
        c, d = divmod(data[-1], 45)[::-1]
        out += [BASE45_ALPHABET[c], BASE45_ALPHABET[d]]
    return "".join(out)


def base45_decode(text: str) -> bytes:
    try:
        values = [_BASE45_INDEX[ch] for ch in text]
    except KeyError:
        raise ValueError("not base45 text") from None
    out = bytearray()
    for i in range(0, len(values), 3):
        chunk = values[i : i + 3]
        if len(chunk) == 3:
            n = chunk[0] + chunk[1] * 45 + chunk[2] * 45 * 45
            if n > 0xFFFF:
                raise ValueError("invalid base45 group")
            out += bytes(divmod(n, 256))
        elif len(chunk) == 2:
            n = chunk[0] + chunk[1] * 45
            if n > 0xFF:
                raise ValueError("invalid base45 group")
            out.append(n)
        else:
            raise ValueError("truncated base45 text")
    return bytes(out)


# ───────────────────────────────────────────────
#  Compression + QR images
# ───────────────────────────────────────────────
def _deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)  # raw DEFLATE, no header
    return compressor.compress(data) + compressor.flush()


def _inflate(data: bytes, limit: int) -> bytes:
    decompressor = zlib.decompressobj(-15)
    try:
        out = decompressor.decompress(data, limit)
    except zlib.error:
        raise ValueError("corrupt compressed data") from None
    if decompressor.unconsumed_tail:
        raise ValueError("decompressed data is too large")
    return out


def qr_image(text: str, error: str = "m") -> dict:
    """PNG (base64) of one QR code, plus its version. Raises QrShareError
    when the text can't fit any QR code at all."""
    try:
        qr = segno.make(text, error=error, micro=False)
    except segno.DataOverflowError:
        raise QrShareError("This is too much data for a single QR code.") from None
    modules = qr.symbol_size(scale=1, border=4)[0]
    # ~8px per module, capped so the image stays around 1,000px or less.
    scale = max(3, min(10, 1000 // modules))
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=4)
    return {
        "png_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "version": qr.version,
        "error_correction": qr.error,
        "dense": qr.version > DENSE_QR_VERSION,
    }


def fits_one_qr(text: str) -> bool:
    try:
        segno.make(text, error="l", micro=False)
        return True
    except segno.DataOverflowError:
        return False


# ───────────────────────────────────────────────
#  2. Blueprint — the design in one code
# ───────────────────────────────────────────────
_STACK_KEYS = (
    "frontend_framework",
    "frontend_language",
    "backend_framework",
    "backend_language",
    "api_style",
)


def _compact_table(table: dict, keep_purpose: bool, keep_seeds: bool) -> dict:
    """A stored (normalized) table minus everything that is a default —
    import parses it back through the same lenient models, which refill
    those defaults, so nothing is lost but bytes."""
    out: dict[str, Any] = {"name": table.get("name", "")}
    if keep_purpose and table.get("purpose"):
        out["purpose"] = table["purpose"]
    out["key_fields"] = list(table.get("key_fields") or [])
    specs = []
    for spec in table.get("field_specs") or []:
        s = {"name": spec.get("name")}
        if spec.get("type"):
            s["type"] = spec["type"]
        if spec.get("nullable") is False:
            s["nullable"] = False
        if spec.get("default") is not None:
            s["default"] = spec["default"]
        if spec.get("unique"):
            s["unique"] = True
        specs.append(s)
    if specs:
        out["field_specs"] = specs
    fks = []
    for fk in table.get("foreign_keys") or []:
        f = {"field": fk.get("field"), "references_table": fk.get("references_table")}
        if fk.get("references_field") not in (None, "", "id"):
            f["references_field"] = fk["references_field"]
        if fk.get("on_delete") not in (None, "", "cascade"):
            f["on_delete"] = fk["on_delete"]
        fks.append(f)
    if fks:
        out["foreign_keys"] = fks
    if table.get("checks"):
        out["checks"] = [
            {"name": c.get("name"), "expression": c.get("expression")}
            for c in table["checks"]
        ]
    indexes = []
    for idx in table.get("indexes") or []:
        i = {"fields": list(idx.get("fields") or [])}
        if idx.get("unique"):
            i["unique"] = True
        indexes.append(i)
    if indexes:
        out["indexes"] = indexes
    if keep_seeds and table.get("seed_rows"):
        out["seed_rows"] = table["seed_rows"]
    return out


def blueprint_payload(project: Any, level: int = 0) -> dict:
    """The design as a plain dict. `level` drops detail in steps so a big
    design can still fit one code: 1 = no descriptive text, 2 = no
    table/endpoint purposes, 3 = no seed rows, 4 = no endpoints."""
    architecture = (getattr(project, "architecture_data", None) or {}).get(
        "architecture"
    ) or {}
    payload: dict[str, Any] = {
        "v": 1,
        "name": getattr(project, "name", "") or "Imported app",
    }
    stack = getattr(project, "selected_stack", None) or {}
    stack = {k: stack[k] for k in _STACK_KEYS if stack.get(k)}
    if stack:
        payload["stack"] = stack
    if level < 1:
        if getattr(project, "description", None):
            payload["description"] = str(project.description)[:500]
        if architecture.get("architecture_summary"):
            payload["summary"] = architecture["architecture_summary"]
        if architecture.get("tech_stack"):
            payload["tech_stack"] = architecture["tech_stack"]
        if architecture.get("third_party_services"):
            payload["services"] = architecture["third_party_services"]
    payload["tables"] = [
        _compact_table(t, keep_purpose=level < 2, keep_seeds=level < 3)
        for t in architecture.get("database_tables") or []
    ]
    if level < 4:
        endpoints = []
        for e in architecture.get("api_endpoints") or []:
            row = [e.get("method", ""), e.get("path", "")]
            if level < 2 and e.get("purpose"):
                row.append(e["purpose"])
            endpoints.append(row)
        if endpoints:
            payload["endpoints"] = endpoints
    return payload


_LEVEL_OMISSIONS = {
    1: "the description, summary, tech stack and services",
    2: "table and endpoint purposes",
    3: "seed rows",
    4: "API endpoints",
}


@dataclass
class Blueprint:
    text: str
    payload: dict
    compressed_bytes: int
    omitted: list[str] = field(default_factory=list)


def encode_blueprint(project: Any) -> Blueprint:
    """The most complete blueprint that still fits one QR code."""
    architecture = (getattr(project, "architecture_data", None) or {}).get(
        "architecture"
    ) or {}
    if not architecture.get("database_tables"):
        raise QrShareError(
            "This project has no database tables yet — a blueprint carries the Architecture design, "
            "so finish the Architecture phase first."
        )
    for level in range(0, 5):
        payload = blueprint_payload(project, level)
        packed = _deflate(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        )
        text = BLUEPRINT_PREFIX + base45_encode(packed)
        if fits_one_qr(text):
            return Blueprint(
                text=text,
                payload=payload,
                compressed_bytes=len(packed),
                omitted=[_LEVEL_OMISSIONS[n] for n in range(1, level + 1)],
            )
    raise QrShareError(
        "This design is too big for one QR code even without its descriptions and endpoints. "
        "Use a download link or a QR sequence instead."
    )


def _str(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def decode_blueprint(text: str) -> dict:
    """The blueprint dict from a scanned code's text — shape-checked, with
    anything unexpected dropped. Raises QrShareError with a readable
    message for text that isn't a usable blueprint."""
    text = (text or "").strip()
    if not text.upper().startswith(BLUEPRINT_PREFIX):
        if text.startswith(SEQUENCE_PREFIX + ":"):
            raise QrShareError(
                "That's one code of a QR sequence — scan it with the VengaiCode mobile app's scanner."
            )
        if text.lower().startswith(("http://", "https://")):
            raise QrShareError(
                "That's a download link — open it in a browser to download the project."
            )
        raise QrShareError("That isn't a VengaiCode blueprint code.")
    try:
        raw = _inflate(
            base45_decode(text[len(BLUEPRINT_PREFIX) :]), MAX_BLUEPRINT_JSON_BYTES
        )
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise QrShareError(
            "This blueprint code is damaged or incomplete — try scanning it again."
        ) from None
    if not isinstance(data, dict) or data.get("v") != 1:
        raise QrShareError(
            "This blueprint was made by a newer VengaiCode — update the app to import it."
        )

    tables = data.get("tables")
    if not isinstance(tables, list) or not tables:
        raise QrShareError("This blueprint has no tables in it.")
    if len(tables) > MAX_BLUEPRINT_TABLES:
        raise QrShareError(
            f"This blueprint has more than {MAX_BLUEPRINT_TABLES} tables."
        )
    endpoints = []
    for row in data.get("endpoints") or []:
        if (
            isinstance(row, list)
            and len(row) >= 2
            and all(isinstance(x, str) for x in row[:3])
        ):
            endpoints.append(
                {
                    "method": row[0].upper()[:10],
                    "path": row[1][:300],
                    "purpose": row[2][:500] if len(row) > 2 else "",
                }
            )
    stack = data.get("stack") if isinstance(data.get("stack"), dict) else {}
    tech = data.get("tech_stack") if isinstance(data.get("tech_stack"), dict) else {}
    services = data.get("services") if isinstance(data.get("services"), list) else []
    return {
        "name": _str(data.get("name"), 255).strip() or "Imported app",
        "description": _str(data.get("description"), 500),
        "summary": _str(data.get("summary"), 5000),
        "stack": {
            k: str(stack[k])[:50] for k in _STACK_KEYS if isinstance(stack.get(k), str)
        },
        "tech_stack": {
            k: _str(tech.get(k), 200)
            for k in ("frontend", "backend", "database", "hosting")
        },
        "services": [s[:200] for s in services if isinstance(s, str)][:50],
        "tables": [t for t in tables if isinstance(t, dict)],
        "endpoints": endpoints[:MAX_BLUEPRINT_ENDPOINTS],
    }


# ───────────────────────────────────────────────
#  3. QR sequence — the whole bundle, many codes
# ───────────────────────────────────────────────
def sequence_payload(name: str, bundle: list[tuple[str, str]]) -> bytes:
    """What the frames carry: one compressed JSON of every file. One
    stream compresses repeated boilerplate across files — measured 2.4x
    smaller than the ZIP of the same files — and the receiving phone
    rebuilds the ZIP from it."""
    doc = {"v": 1, "name": name, "files": [[path, content] for path, content in bundle]}
    return _deflate(
        json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def build_sequence(
    name: str, bundle: list[tuple[str, str]], frame_bytes: int = DEFAULT_FRAME_BYTES
) -> dict:
    if not MIN_FRAME_BYTES <= frame_bytes <= MAX_FRAME_BYTES:
        raise QrShareError(
            f"Frame size must be between {MIN_FRAME_BYTES} and {MAX_FRAME_BYTES} bytes."
        )
    payload = sequence_payload(name, bundle)
    count = -(-len(payload) // frame_bytes)
    if count > MAX_SEQUENCE_FRAMES:
        raise QrShareError(
            f"This project needs {count} QR codes — more than {MAX_SEQUENCE_FRAMES}, which would take too long "
            "to scan. Use a download link instead."
        )
    sid = f"{zlib.crc32(payload) & 0xFFFFFFFF:08X}"
    frames = [
        f"{SEQUENCE_PREFIX}:{sid}:{i}:{count}:{base45_encode(payload[i * frame_bytes : (i + 1) * frame_bytes])}"
        for i in range(count)
    ]
    return {
        "sid": sid,
        "frames": frames,
        "frame_count": count,
        "payload_bytes": len(payload),
        "file_count": len(bundle),
        "name": name,
    }


def decode_sequence(frames: list[str]) -> dict:
    """Reassembles scanned frames (any order, duplicates fine) into
    {"name", "files": [[path, content], ...]} — the Python twin of the
    mobile app's receiver, used by the tests to prove the format."""
    parts: dict[int, bytes] = {}
    sid = count = None
    for frame in frames:
        prefix, f_sid, index, total, data = frame.split(":", 4)
        if prefix != SEQUENCE_PREFIX:
            raise QrShareError("Not a VengaiCode QR sequence frame.")
        if sid is None:
            sid, count = f_sid, int(total)
        elif f_sid != sid or int(total) != count:
            # The same project cut into a different frame size keeps its
            # SID (same payload), so the count tells those streams apart.
            raise QrShareError("These codes come from two different transfers.")
        parts[int(index)] = base45_decode(data)
    missing = [i for i in range(count or 0) if i not in parts]
    if missing:
        raise QrShareError(f"Still missing {len(missing)} of {count} codes.")
    payload = b"".join(parts[i] for i in range(count))
    if f"{zlib.crc32(payload) & 0xFFFFFFFF:08X}" != sid:
        raise QrShareError(
            "The scanned data didn't check out — scan the sequence again."
        )
    return json.loads(_inflate(payload, 200_000_000).decode("utf-8"))
