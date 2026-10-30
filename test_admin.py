"""Run: uv run --no-project --with fastapi --with bcrypt --with httpx --with pytest --with pymongo python -m pytest test_admin.py -q"""
import base64
import hashlib
import hmac
import json
import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
import main

ADMIN = "koteshwarraoravipati@gmail.com"
MEMBER = "member@gmail.com"


def opportunity(**changes):
    return {"title": "Engineering workshop", "organization": "Example University", "institution": "Example University", "sourceUrl": "https://example.ac.in/events", "applyUrl": "https://example.ac.in/apply", "sourceStatus": "verified", "visibility": "published", "startAt": "2026-11-12", "summary": "Public details", **changes}


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name, filename in (("USERS_FILE", "users.json"), ("SAVED_FILE", "saved.json"), ("EVENTS_FILE", "events.json"), ("OVERRIDES_FILE", "event_overrides.json"), ("SESSION_SECRET_FILE", "session_secret")):
        monkeypatch.setattr(main, name, tmp_path / filename)
    monkeypatch.setattr(main, "MONGO_URI", "")
    monkeypatch.setattr(main, "SECRET", None)
    monkeypatch.setattr(main, "ADMIN_EMAILS", {ADMIN})
    main.write_json(main.USERS_FILE, {ADMIN: {"email": ADMIN}, MEMBER: {"email": MEMBER, "is_admin": True}})
    main.write_json(main.EVENTS_FILE, [{"id": "seed-1", **opportunity(), "tags": ["engineering"], "mode": "Online"}])
    with TestClient(main.app) as api:
        yield api


def headers(email=ADMIN):
    return {"Authorization": "Bearer " + main.token_for(email)}


def test_authorization_and_server_allowlist(client):
    for method, path, body in [("GET", "/api/admin/events", None), ("POST", "/api/admin/events", opportunity()), ("PUT", "/api/admin/events/seed-1", opportunity()), ("DELETE", "/api/admin/events/seed-1", None)]:
        assert client.request(method, path, json=body).status_code == 401
        assert client.request(method, path, json=body, headers=headers(MEMBER)).status_code == 403
    assert client.get("/api/auth/me", headers=headers()).json()["user"]["is_admin"] is True
    assert client.get("/api/auth/me", headers=headers(MEMBER)).json()["user"]["is_admin"] is False


def test_create_edit_delete_and_seed_untouched(client):
    original = main.EVENTS_FILE.read_bytes()
    assert client.get("/api/admin/events", headers=headers()).json()["storage"] == "local"
    created = client.post("/api/admin/events", json=opportunity(), headers=headers())
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    assert event_id in {e["id"] for e in main.load_events()}
    update = client.put("/api/admin/events/seed-1", json=opportunity(title="Updated workshop"), headers=headers())
    assert update.status_code == 200, update.text
    assert update.json()["tags"] == ["engineering"]
    assert update.json()["mode"] == "Online"
    assert next(e for e in main.load_events() if e["id"] == "seed-1")["title"] == "Updated workshop"
    public = client.get("/api/catalog/overrides").json()
    assert len(public["events"]) == 2
    assert client.delete(f"/api/admin/events/{event_id}", headers=headers()).json() == {"deleted": event_id}
    assert event_id not in {e["id"] for e in main.load_events()}
    assert event_id in client.get("/api/catalog/overrides").json()["deleted_ids"]
    assert main.EVENTS_FILE.read_bytes() == original
    assert client.put("/api/admin/events/missing", json=opportunity(), headers=headers()).status_code == 200
    assert client.delete("/api/admin/events/missing", headers=headers()).status_code == 200


@pytest.mark.parametrize("visibility", ["draft", "archived"])
def test_hidden_records_never_exposed(client, visibility):
    hidden = opportunity(title="Private draft content", visibility=visibility)
    assert client.put("/api/admin/events/seed-1", json=hidden, headers=headers()).status_code == 200
    public = client.get("/api/catalog/overrides")
    assert public.json() == {"events": [], "deleted_ids": ["seed-1"]}
    assert "Private draft content" not in public.text
    assert main.load_events() == []
    assert client.get("/api/events", headers=headers(MEMBER)).json() == []
    assert client.get("/api/admin/events", headers=headers()).json()["events"][0]["title"] == "Private draft content"


@pytest.mark.parametrize("changes", [
    {"sourceUrl": "http://example.ac.in"}, {"applyUrl": "javascript:alert(1)"},
    {"applyUrl": "https://user:password@example.ac.in"}, {"applyUrl": "https://example.ac.in/ bad"},
    {"sourceUrl": "https://example.com"}, {"sourceUrl": "https://example.ac.in.evil.com"},
    {"startAt": "tomorrow"}, {"startAt": "2026-02-30"}, {"startAt": "20261112"},
    {"startAt": None}, {"sourceStatus": "fake"}, {"visibility": "private"},
    {"title": " "}, {"institution": ""}, {"organization": "x" * 241},
    {"description": "x" * 12001}, {"tags": ["x" * 101]}, {"$set": {"title": "injected"}},
    {"sourceUrl": {"$ne": None}}, {"confidence": float("inf")},
])
def test_validation(client, changes):
    body = opportunity(**changes)
    if changes.get("confidence") == float("inf"):
        # JSON has no Infinity; validate the model directly.
        with pytest.raises(ValueError):
            main.AdminEvent.model_validate(body)
        return
    response = client.post("/api/admin/events", json=body, headers=headers())
    assert response.status_code == 422, response.text
    assert not main.OVERRIDES_FILE.exists()


def test_explicit_status_and_review_and_dates(client):
    body = opportunity()
    del body["sourceStatus"]
    assert client.post("/api/admin/events", json=body, headers=headers()).status_code == 422
    body = opportunity(sourceStatus="needs_review", visibility="needs_review", sourceUrl="https://example.com", startAt="2026-11-12T12:30:00+05:30")
    response = client.post("/api/admin/events", json=body, headers=headers())
    assert response.status_code == 201, response.text
    assert client.get("/api/catalog/overrides").json()["events"][0]["sourceStatus"] == "needs_review"


def test_default_key_forgery_and_persistence(client, monkeypatch):
    payload = base64.urlsafe_b64encode(json.dumps({"email": ADMIN, "exp": int(time.time()) + 1000}).encode()).decode().rstrip("=")
    signature = hmac.new(b"opportunity-atlas-dev-secret-change-me", payload.encode(), hashlib.sha256).hexdigest()
    assert client.get("/api/admin/events", headers={"Authorization": f"Bearer {payload}.{signature}"}).status_code == 401
    token = main.token_for(ADMIN)
    first = main.session_secret()
    assert len(first) >= 64
    monkeypatch.setattr(main, "SECRET", None)
    assert main.session_secret() == first
    assert client.get("/api/admin/events", headers={"Authorization": "Bearer " + token}).status_code == 200
    explicit = b"explicit-configured-secret"
    monkeypatch.setattr(main, "SECRET", explicit)
    assert main.session_secret() == explicit


def test_no_stale_overlay_cache(client):
    assert len(main.load_events()) == 1
    main.write_json(main.OVERRIDES_FILE, {"seed-1": {"deleted": True}})
    assert main.load_events() == []


class Collection:
    def __init__(self):
        self.docs = {}
    def find(self, query):
        return list(deepcopy(self.docs).values())
    def replace_one(self, query, doc, upsert=False):
        self.docs[query["_id"]] = deepcopy(doc)
    def find_one_and_update(self, query, update, upsert=False, return_document=False):
        self.docs.setdefault(query["_id"], {"_id": query["_id"], **update["$setOnInsert"]})
        return deepcopy(self.docs[query["_id"]])


def test_mongodb_overlay_and_shared_secret(client, monkeypatch):
    collections = {}
    monkeypatch.setattr(main, "MONGO_URI", "mongodb://mocked")
    monkeypatch.setattr(main, "mongo_call", lambda name, operation: operation(collections.setdefault(name, Collection())))
    # Seed mocked users rather than bypassing the authorization dependency.
    collections["users"] = Collection()
    collections["users"].docs[ADMIN] = {"_id": ADMIN, "email": ADMIN}
    response = client.post("/api/admin/events", json=opportunity(), headers=headers())
    assert response.status_code == 201, response.text
    assert client.get("/api/admin/events", headers=headers()).json()["storage"] == "mongodb"
    first = main.session_secret()
    monkeypatch.setattr(main, "SECRET", None)
    assert main.session_secret() == first
    event_id = response.json()["id"]
    assert client.put(f"/api/admin/events/{event_id}", json=opportunity(visibility="draft"), headers=headers()).status_code == 200
    assert event_id in client.get("/api/catalog/overrides").json()["deleted_ids"]
    assert client.delete(f"/api/admin/events/{event_id}", headers=headers()).status_code == 200
    assert collections["event_overrides"].docs[event_id]["deleted"] is True


def test_admin_html_route(client, tmp_path, monkeypatch):
    # Avoid writing production frontend files owned by another implementation task.
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / "admin.html").write_text("<h1>Admin page fixture</h1>", encoding="utf-8")
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Admin page fixture" in response.text


def test_invalid_legacy_metadata_does_not_block_valid_edit(client):
    main.write_json(main.EVENTS_FILE, [{"id": "legacy", **opportunity(), "confidence": "unknown", "tags": {"$set": "unsafe"}}])
    response = client.put("/api/admin/events/legacy", json=opportunity(), headers=headers())
    assert response.status_code == 200, response.text
    assert response.json()["confidence"] is None
    assert isinstance(response.json()["tags"], list)


def test_public_registration_cannot_claim_admin_email(client):
    main.write_json(main.USERS_FILE, {})
    response = client.post("/api/auth/register", json={"email": "  KOTESHWARRAORAVIPATI@gmail.com  ", "password": "valid-password", "recovery_pin": "1234"})
    assert response.status_code == 403
    assert main.read_users() == {}


def test_overrides_no_store_and_empty_optional_fields(client):
    body = opportunity(type="", state="", district="", location="", branch="", year="", summary="", description="", eligibility="", startAt=None, endAt=None, deadlineAt=None, visibility="draft")
    created = client.post("/api/admin/events", json=body, headers=headers())
    assert created.status_code == 201, created.text
    response = client.get("/api/catalog/overrides")
    assert response.headers["cache-control"] == "no-store"
    assert created.json()["id"] in response.json()["deleted_ids"]


def test_frontend_only_ids_support_edit_and_tombstone(client):
    response = client.put("/api/admin/events/static-only-id", json=opportunity(), headers=headers())
    assert response.status_code == 200, response.text
    assert response.json()["id"] == "static-only-id"
    assert "static-only-id" in {e["id"] for e in client.get("/api/catalog/overrides").json()["events"]}
    assert client.delete("/api/admin/events/another-static-only-id", headers=headers()).status_code == 200
    assert "another-static-only-id" in client.get("/api/catalog/overrides").json()["deleted_ids"]
    assert client.delete("/api/admin/events/another-static-only-id", headers=headers()).status_code == 200
    assert client.put("/api/admin/events/" + "x" * 201, json=opportunity(), headers=headers()).status_code == 422
