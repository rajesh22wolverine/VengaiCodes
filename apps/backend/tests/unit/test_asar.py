"""Verifies parse_asar() against a hand-constructed synthetic archive built
independently from the same documented Chromium-Pickle-based ASAR format —
not against a real Electron-produced .asar file, since none was available
to fetch in this sandboxed environment. The encoder here (build_test_asar)
is deliberately written as its own standalone struct.pack sequence, not by
calling any of parse_asar()'s internals, so this is a genuine two-sided
check of the format rather than a self-consistent round-trip that could
share the same misunderstanding.
"""

import json
import struct

import pytest

from app.api.v1.reverse_engineer import AsarParseError, parse_asar


def build_test_asar(files: dict[str, bytes]) -> bytes:
    """Hand-encodes a minimal valid asar archive, following the same spec
    parse_asar() documents, independently of its implementation."""
    header_files = {}
    file_data = b""
    offset = 0
    for path, content in files.items():
        header_files[path] = {"size": len(content), "offset": str(offset)}
        file_data += content
        offset += len(content)

    header_json = json.dumps({"files": header_files}).encode("utf-8")
    str_len = len(header_json)
    # Pickle pads the (length-field + string-bytes) payload to a 4-byte boundary.
    pad = (4 - ((4 + str_len) % 4)) % 4
    header_pickle_payload = struct.pack("<I", str_len) + header_json + (b"\x00" * pad)
    header_pickle_bytes = (
        struct.pack("<I", len(header_pickle_payload)) + header_pickle_payload
    )

    outer = struct.pack("<I", 4) + struct.pack("<I", len(header_pickle_bytes))
    return outer + header_pickle_bytes + file_data


def test_parse_asar_round_trips_a_single_file():
    raw = build_test_asar({"hello.txt": b"Hello, ASAR!"})
    assert parse_asar(raw) == {"hello.txt": b"Hello, ASAR!"}


def test_parse_asar_round_trips_multiple_files_and_nested_dirs():
    files = {
        "index.ts": b"import electron from 'electron';\nconsole.log('shell entry');",
        "dir/nested.js": b"console.log(1)",
        "dir/deeper/file.json": b'{"a": 1}',
    }
    raw = build_test_asar(files)
    assert parse_asar(raw) == files


def test_parse_asar_handles_content_requiring_padding():
    # String lengths chosen so the header JSON's byte length lands on
    # different mod-4 remainders, exercising the padding math at each case.
    for pad_len in range(0, 8):
        files = {("x" * pad_len + ".txt" if pad_len else "a.txt"): b"content"}
        raw = build_test_asar(files)
        assert parse_asar(raw) == files


def test_parse_asar_skips_unpacked_entries():
    header_files = {
        "regular.js": {"size": 4, "offset": "0"},
        "big-binary.node": {"unpacked": True},
    }
    header_json = json.dumps({"files": header_files}).encode("utf-8")
    str_len = len(header_json)
    pad = (4 - ((4 + str_len) % 4)) % 4
    header_pickle_payload = struct.pack("<I", str_len) + header_json + (b"\x00" * pad)
    header_pickle_bytes = (
        struct.pack("<I", len(header_pickle_payload)) + header_pickle_payload
    )
    raw = (
        struct.pack("<I", 4)
        + struct.pack("<I", len(header_pickle_bytes))
        + header_pickle_bytes
        + b"abcd"
    )

    result = parse_asar(raw)
    assert result == {"regular.js": b"abcd"}
    assert "big-binary.node" not in result


def test_parse_asar_rejects_too_small_input():
    with pytest.raises(AsarParseError):
        parse_asar(b"\x00\x01\x02")


def test_parse_asar_rejects_header_extending_past_file_end():
    with pytest.raises(AsarParseError):
        parse_asar(struct.pack("<I", 4) + struct.pack("<I", 999999))


def test_parse_asar_rejects_non_json_header():
    bogus_string = b"not json"
    pad = (4 - ((4 + len(bogus_string)) % 4)) % 4
    header_pickle_payload = (
        struct.pack("<I", len(bogus_string)) + bogus_string + (b"\x00" * pad)
    )
    header_pickle_bytes = (
        struct.pack("<I", len(header_pickle_payload)) + header_pickle_payload
    )
    raw = (
        struct.pack("<I", 4)
        + struct.pack("<I", len(header_pickle_bytes))
        + header_pickle_bytes
    )
    with pytest.raises(AsarParseError):
        parse_asar(raw)


def test_parse_asar_skips_out_of_range_entry_instead_of_crashing():
    header_files = {
        "ok.js": {"size": 3, "offset": "0"},
        "bad.js": {"size": 999999, "offset": "0"},
    }
    header_json = json.dumps({"files": header_files}).encode("utf-8")
    str_len = len(header_json)
    pad = (4 - ((4 + str_len) % 4)) % 4
    header_pickle_payload = struct.pack("<I", str_len) + header_json + (b"\x00" * pad)
    header_pickle_bytes = (
        struct.pack("<I", len(header_pickle_payload)) + header_pickle_payload
    )
    raw = (
        struct.pack("<I", 4)
        + struct.pack("<I", len(header_pickle_bytes))
        + header_pickle_bytes
        + b"abc"
    )

    result = parse_asar(raw)
    assert result == {"ok.js": b"abc"}
    assert "bad.js" not in result
