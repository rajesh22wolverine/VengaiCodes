"""
Share via QR (api/v1/share.py + services/qr_share.py) — the three options
through the real API on a real SQLite database:
  1. download link: create -> public download -> list -> revoke/expire
  2. blueprint: one code -> inspect -> import -> the No-AI generator
     rebuilds the SAME code from the imported project
  3. QR sequence: frames -> reassembled (any order) -> the same files
"""

import asyncio
import base64
import copy
import io
import json
import random
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import segno
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai import codegen_deterministic as dc
from app.ai import db_schema
from app.api.v1.auth import get_current_active_user
from app.api.v1.share import link_reach
from app.core.database import Base, get_db
from app.main import app
from app.models.project import Project
from app.models.project_share import ProjectShareLink
from app.models.user import User
from app.services import qr_share

STACK = {
    "frontend_framework": "react",
    "frontend_language": "javascript",
    "backend_framework": "fastapi",
    "backend_language": "python",
    "api_style": "rest",
}
STACK_INFO = {
    **{k: STACK[k] for k in ("frontend_framework", "backend_framework", "api_style")}
}
STACK_INFO.update(codegen_target="react_fastapi", source="selected_stack")

TABLES = db_schema.normalize_tables(
    [
        {
            "name": "authors",
            "purpose": "People who write",
            "key_fields": ["name", "handle", "is_active"],
            "field_specs": [
                {"name": "handle", "nullable": False, "unique": True},
                {"name": "is_active", "type": "boolean", "default": False},
            ],
            "seed_rows": [{"name": "Ann", "handle": "ann"}],
        },
        {
            "name": "books",
            "purpose": "Things they wrote",
            "key_fields": ["title", "author_id", "price", "published_on"],
            "field_specs": [
                {"name": "price", "type": "decimal", "nullable": False, "default": "0"},
                {"name": "published_on", "type": "date"},
            ],
            "foreign_keys": [
                {
                    "field": "author_id",
                    "references_table": "authors",
                    "on_delete": "set_null",
                }
            ],
            "checks": [{"name": "price ok", "expression": "price >= 0"}],
            "indexes": [{"fields": ["title", "author_id"], "unique": True}],
        },
    ],
    "fastapi",
)
ARCHITECTURE = {
    "architecture_summary": "A tiny library app.",
    "tech_stack": {
        "frontend": "React",
        "backend": "FastAPI",
        "database": "SQLite",
        "hosting": "Desktop",
    },
    "database_tables": TABLES,
    "api_endpoints": [{"method": "GET", "path": "/api/books", "purpose": "List books"}],
    "third_party_services": [],
}


def _user() -> User:
    return User(
        id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex}@example.com",
        username=uuid.uuid4().hex[:12],
        hashed_password="x",
        full_name="Test",
    )


def _project(owner: User, **extra) -> Project:
    return Project(
        id=str(uuid.uuid4()),
        user_id=owner.id,
        name="Little Library",
        description="Books and their authors",
        selected_stack=STACK,
        architecture_data={
            "architecture": copy.deepcopy(ARCHITECTURE),
            "user_approved": True,
        },
        **extra,
    )


@pytest.fixture
def api(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'share.db'}", poolclass=NullPool
    )
    sessions = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    owner, stranger = _user(), _user()
    project = _project(owner)
    project.codegen_data = dc.build_deterministic_codegen_data(project, STACK_INFO)
    theirs = _project(stranger)

    async def setup():
        # Tables only — same duplicate-index workaround as the other route tests.
        stashed = {t.name: list(t.indexes) for t in Base.metadata.tables.values()}
        for table in Base.metadata.tables.values():
            table.indexes.clear()
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            for table in Base.metadata.tables.values():
                table.indexes.update(stashed.get(table.name, []))
        async with sessions() as db:
            db.add_all([owner, stranger, project, theirs])
            await db.commit()

    asyncio.run(setup())

    async def override_get_db():
        async with sessions() as session:
            yield session

    async def run(fn):
        async with sessions() as db:
            result = await fn(db)
            await db.commit()
            return result

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: owner
    # Not `with TestClient(app)`: the lifespan would connect to the real DATABASE_URL.
    yield SimpleNamespace(
        client=TestClient(app),
        project=project,
        theirs=theirs,
        run=lambda fn: asyncio.run(run(fn)),
    )
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def _png(qr: dict) -> bytes:
    data = base64.b64decode(qr["png_base64"])
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return data


# ─── base45 ───
@pytest.mark.parametrize(
    "raw,encoded",
    [
        (b"AB", "BB8"),
        (b"Hello!!", "%69 VD92EX0"),
        (b"base-45", "UJCLQE7W581"),
        (b"ietf!", "QED8WEX0"),
    ],
)
def test_base45_matches_rfc_9285(raw, encoded):
    assert qr_share.base45_encode(raw) == encoded
    assert qr_share.base45_decode(encoded) == raw


def test_base45_round_trips_and_refuses_garbage():
    rng = random.Random(7)
    for n in range(200):
        data = bytes(rng.randrange(256) for _ in range(n))
        assert qr_share.base45_decode(qr_share.base45_encode(data)) == data
    for bad in ("abc", "GGW", "A"):  # lower case, a group over 65535, a dangling char
        with pytest.raises(ValueError):
            qr_share.base45_decode(bad)


# ─── 1. Download link ───
@pytest.mark.parametrize(
    "url,reach",
    [
        ("http://localhost:8000/x", "this_device"),
        ("http://127.0.0.1:8000/x", "this_device"),
        ("http://192.168.1.20:8000/x", "same_network"),
        ("http://my-pc.local/x", "same_network"),
        ("https://api.example.com/x", "anyone"),
    ],
)
def test_link_reach(url, reach):
    assert link_reach(url) == reach


def test_download_link_lifecycle(api):
    c = api.client
    r = c.post(f"/api/v1/share/{api.project.id}/links", json={"expires_in_hours": 24})
    assert r.status_code == 201, r.text
    body = r.json()
    url, link_id = body["url"], body["link"]["id"]
    token = url.rsplit("/", 1)[1]
    assert "/api/v1/share/d/" in url and len(token) >= 20
    _png(body["qr"])

    # Only a hash of the token is stored.
    stored = api.run(lambda db: db.get(ProjectShareLink, link_id))
    assert stored.token_hash != token and len(stored.token_hash) == 64

    # Anyone with the link gets the ZIP — code and documents — without signing in.
    app.dependency_overrides.pop(get_current_active_user)
    r = c.get(f"/api/v1/share/d/{token}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert (
        "README.md" in names
        and "docs/overview.md" in names
        and "backend/models/books.py" in names
    )

    listed = c.get(f"/api/v1/share/{api.project.id}/links")
    assert listed.status_code == 401  # listing needs the owner
    app.dependency_overrides[get_current_active_user] = lambda: api.run(
        lambda db: db.get(User, api.project.user_id)
    )
    links = c.get(f"/api/v1/share/{api.project.id}/links").json()["links"]
    assert [(link["id"], link["download_count"], link["active"]) for link in links] == [
        (link_id, 1, True)
    ]
    assert "token" not in json.dumps(links)

    assert (
        c.delete(f"/api/v1/share/{api.project.id}/links/{link_id}").json()["link"][
            "active"
        ]
        is False
    )
    r = c.get(f"/api/v1/share/d/{token}")
    assert r.status_code == 404 and "isn't available" in r.text
    assert c.get("/api/v1/share/d/not-a-real-token").status_code == 404


def test_an_expired_link_stops_working(api):
    c = api.client
    token = (
        c.post(f"/api/v1/share/{api.project.id}/links", json={"expires_in_hours": 1})
        .json()["url"]
        .rsplit("/", 1)[1]
    )

    async def expire(db):
        link = (await db.execute(select(ProjectShareLink))).scalar_one()
        link.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    api.run(expire)
    assert c.get(f"/api/v1/share/d/{token}").status_code == 404


def test_links_are_owner_only(api):
    c = api.client
    assert c.post(f"/api/v1/share/{api.theirs.id}/links", json={}).status_code == 404
    assert (
        c.post(
            f"/api/v1/share/{api.project.id}/links", json={"expires_in_hours": 99999}
        ).status_code
        == 422
    )


# ─── 2. Blueprint ───
def test_blueprint_rebuilds_the_same_code(api):
    c = api.client
    r = c.get(f"/api/v1/share/{api.project.id}/blueprint")
    assert r.status_code == 200, r.text
    body = r.json()
    text = body["text"]
    assert (
        text.startswith("VGC1:") and body["omitted"] == [] and body["table_count"] == 2
    )
    assert segno.make(text, error="l", micro=False).mode == "alphanumeric"
    _png(body["qr"])

    inspected = c.post("/api/v1/share/blueprint/inspect", json={"text": text}).json()
    assert inspected["name"] == "Little Library" and inspected["table_names"] == [
        "authors",
        "books",
    ]

    r = c.post("/api/v1/share/blueprint/import", json={"text": text})
    assert r.status_code == 201, r.text
    imported = api.run(lambda db: db.get(Project, r.json()["project_id"]))
    assert imported.architecture_data["user_approved"] is True
    assert imported.architecture_data["architecture"]["database_tables"] == TABLES
    assert imported.selected_stack["backend_framework"] == "fastapi"
    assert "erDiagram" in imported.uml_diagrams["erd"]

    # The imported design regenerates byte-identical code (migration files
    # only differ by their creation timestamps).
    rebuilt = dc.build_deterministic_codegen_data(imported, STACK_INFO)

    def code(data):
        return {
            f["path"]: f["content"]
            for f in data["codegen"]["files"]
            if "/migrations/" not in f["path"]
        }

    assert code(rebuilt) == code(api.project.codegen_data)


def test_a_big_design_drops_detail_before_giving_up(api):
    wide = copy.deepcopy(ARCHITECTURE)
    wide["architecture_summary"] = "".join(
        f"word{i} " for i in range(3000)
    )  # won't compress away
    project = SimpleNamespace(
        name="Big",
        description="",
        selected_stack=STACK,
        architecture_data={"architecture": wide},
    )
    blueprint = qr_share.encode_blueprint(project)
    assert blueprint.omitted == ["the description, summary, tech stack and services"]
    assert "summary" not in blueprint.payload and len(blueprint.payload["tables"]) == 2

    huge = copy.deepcopy(ARCHITECTURE)
    huge["database_tables"] = [
        {
            "name": f"t{i}_{uuid.uuid4().hex}",
            "key_fields": [uuid.uuid4().hex for _ in range(12)],
        }
        for i in range(40)
    ]
    project.architecture_data = {"architecture": huge}
    with pytest.raises(qr_share.QrShareError, match="too big for one QR code"):
        qr_share.encode_blueprint(project)


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("hello", "isn't a VengaiCode blueprint"),
        ("https://example.com/x", "download link"),
        ("VGS1:ABCD1234:0:3:AAA", "one code of a QR sequence"),
        ("VGC1:ZZZZ", "damaged or incomplete"),
    ],
)
def test_import_refuses_what_isnt_a_blueprint(api, text, fragment):
    r = api.client.post("/api/v1/share/blueprint/import", json={"text": text})
    assert r.status_code == 400 and fragment in r.json()["detail"]


def test_a_decompression_bomb_is_refused():
    bomb = qr_share._deflate(b"[" + b" " * 5_000_000 + b"]")
    with pytest.raises(qr_share.QrShareError, match="damaged or incomplete"):
        qr_share.decode_blueprint(
            qr_share.BLUEPRINT_PREFIX + qr_share.base45_encode(bomb)
        )


def test_a_project_without_tables_has_no_blueprint(api):
    project = SimpleNamespace(
        name="x", description="", selected_stack=None, architecture_data=None
    )
    with pytest.raises(qr_share.QrShareError, match="no database tables yet"):
        qr_share.encode_blueprint(project)


# ─── 3. QR sequence ───
def test_sequence_carries_every_file_in_any_scan_order(api):
    c = api.client
    r = c.get(f"/api/v1/share/{api.project.id}/sequence", params={"frame_bytes": 300})
    assert r.status_code == 200, r.text
    body = r.json()
    frames = body["frames"]
    assert body["frame_count"] == len(frames) > 5 and body["has_code"] is True
    for frame in frames:
        assert frame.startswith(f"VGS1:{body['sid']}:")
        assert segno.make(frame, error="m", micro=False).mode == "alphanumeric"

    # A camera sees frames out of order and more than once.
    scanned = frames[::-1] + random.Random(3).sample(frames, 4)
    decoded = qr_share.decode_sequence(scanned)
    expected = [
        [path, content]
        for path, content in __import__(
            "app.api.v1.export", fromlist=["x"]
        ).export_bundle_files(api.project)
    ]
    assert decoded["name"] == "Little Library"
    assert [p for p, _ in decoded["files"]] == [p for p, _ in expected]
    assert decoded["files"] == expected

    with pytest.raises(qr_share.QrShareError, match="Still missing 1"):
        qr_share.decode_sequence(frames[1:])
    other = c.get(
        f"/api/v1/share/{api.project.id}/sequence", params={"frame_bytes": 400}
    ).json()["frames"]
    with pytest.raises(qr_share.QrShareError, match="two different transfers"):
        qr_share.decode_sequence(frames[:2] + other[:1])
    tampered = frames[:]
    head, data = tampered[0].rsplit(":", 1)
    tampered[0] = f"{head}:{'0' if data[0] != '0' else '1'}{data[1:]}"
    with pytest.raises(qr_share.QrShareError, match="didn't check out"):
        qr_share.decode_sequence(tampered)


def test_sequence_frame_size_is_bounded(api):
    assert (
        api.client.get(
            f"/api/v1/share/{api.project.id}/sequence", params={"frame_bytes": 50}
        ).status_code
        == 400
    )
    assert api.client.get(f"/api/v1/share/{api.theirs.id}/sequence").status_code == 404
