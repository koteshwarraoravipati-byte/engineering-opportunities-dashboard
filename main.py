from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import bcrypt
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
USERS_FILE = DATA / "users.json"
SAVED_FILE = DATA / "saved.json"
EVENTS_FILE = ROOT / "events.json"
COLLEGES_FILE = ROOT / "colleges.json"
if not EVENTS_FILE.exists(): EVENTS_FILE = ROOT.parent / "events.json"
SECRET = os.getenv("SESSION_SECRET", "opportunity-atlas-dev-secret-change-me").encode()
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@gmail\.com$", re.I)
EMAIL_STRIP_CHARS = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)
LOCK = threading.Lock()

def normalize_email(value: str) -> str:
    """Return one stable key for the same Gmail address across all auth paths."""
    return str(value or "").translate(EMAIL_STRIP_CHARS).strip().casefold()

def normalize_users(raw: Any) -> dict[str, dict[str, Any]]:
    """Migrate legacy keys and discard malformed records before auth lookups."""
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        email = normalize_email(str(value.get("email") or key))
        if not EMAIL_RE.fullmatch(email):
            continue
        user = dict(value)
        user["email"] = email
        previous = normalized.get(email)
        if previous is None or str(user.get("created_at") or "") >= str(previous.get("created_at") or ""):
            normalized[email] = user
    return normalized

MONGO_URI = os.getenv("MONGODB_URI", "").strip()
MONGO_DB_NAME = os.getenv("MONGODB_DB", "opportunity_atlas").strip() or "opportunity_atlas"
_MONGO_CLIENT: Any = None
_MONGO_UNAVAILABLE = False
_MONGO_LOCK = threading.Lock()

def mongo_collection(name: str) -> Any:
    """Return a reachable MongoDB collection, or None for the JSON fallback."""
    global _MONGO_CLIENT, _MONGO_UNAVAILABLE
    if _MONGO_UNAVAILABLE or not MONGO_URI:
        return None
    try:
        from pymongo import MongoClient
        with _MONGO_LOCK:
            if _MONGO_CLIENT is None:
                client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000, connectTimeoutMS=3000)
                client.admin.command("ping")
                _MONGO_CLIENT = client
        collection = _MONGO_CLIENT[MONGO_DB_NAME][name]
        collection.create_index("_id", unique=True)
        return collection
    except Exception:
        _MONGO_UNAVAILABLE = True
        return None

def read_users() -> dict[str, dict[str, Any]]:
    collection = mongo_collection("users")
    if collection is not None:
        try:
            docs = list(collection.find({}))
            users = {str(doc["_id"]): {k: v for k, v in doc.items() if k != "_id"} for doc in docs if doc.get("_id")}
            return normalize_users(users)
        except Exception:
            pass
    return normalize_users(read_json(USERS_FILE, {}))

def write_users(users: dict[str, dict[str, Any]]) -> None:
    collection = mongo_collection("users")
    if collection is not None:
        try:
            for email, user in users.items():
                collection.replace_one({"_id": email}, {"_id": email, **user}, upsert=True)
            if users:
                collection.delete_many({"_id": {"$nin": list(users)}})
            else:
                collection.delete_many({})
            return
        except Exception:
            pass
    write_json(USERS_FILE, users)

def read_saved() -> dict[str, list[str]]:
    collection = mongo_collection("saved")
    if collection is not None:
        try:
            return {str(doc["_id"]): list(doc.get("event_ids") or []) for doc in collection.find({}) if doc.get("_id")}
        except Exception:
            pass
    raw = read_json(SAVED_FILE, {})
    return raw if isinstance(raw, dict) else {}

def write_saved(saved: dict[str, list[str]]) -> None:
    collection = mongo_collection("saved")
    if collection is not None:
        try:
            for email, event_ids in saved.items():
                collection.replace_one({"_id": email}, {"_id": email, "event_ids": list(dict.fromkeys(event_ids))}, upsert=True)
            if saved:
                collection.delete_many({"_id": {"$nin": list(saved)}})
            else:
                collection.delete_many({})
            return
        except Exception:
            pass
    write_json(SAVED_FILE, saved)

app = FastAPI(title="Opportunity Atlas API", version="2.0.0")
configured_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
origins = ["*"] if "*" in configured_origins else list(dict.fromkeys(configured_origins + ["https://eod-warangal.vercel.app", "https://engineering-opportunities-dashboard.vercel.app"]))
app.add_middleware(CORSMiddleware, allow_origins=origins if origins else ["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

# Public records include verified opportunities and clearly labelled source leads; no synthetic records are generated.
class Credentials(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=80)

class RegisterCredentials(Credentials):
    recovery_pin: str = Field(min_length=4, max_length=12)

class PasswordReset(BaseModel):
    email: str
    recovery_pin: str = Field(min_length=4, max_length=12)
    new_password: str = Field(min_length=8, max_length=128)

class SavedRequest(BaseModel):
    event_id: str

def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default

def write_json(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temp.replace(path)

def normalize_event(raw: dict[str, Any], index: int) -> dict[str, Any]:
    return {"id": str(raw.get("id") or raw.get("event_id") or f"opportunity-{index}"), "title": raw.get("title") or raw.get("name") or "Engineering opportunity", "organization": raw.get("organization") or raw.get("organizer") or raw.get("company") or "Local engineering community", "organizer": raw.get("organizer") or raw.get("organization") or raw.get("company") or "Local engineering community", "institution": raw.get("institution") or raw.get("college") or raw.get("organization") or "Warangal engineering community", "location": raw.get("location") or raw.get("venue") or "Warangal, Telangana", "venue": raw.get("venue") or raw.get("location") or "Warangal, Telangana", "state": raw.get("state") or "Telangana", "district": raw.get("district") or raw.get("area") or "Warangal", "area": raw.get("area") or raw.get("district") or "Warangal", "college": raw.get("college") or raw.get("institution") or "Telangana engineering college", "branch": raw.get("branch") or raw.get("eligibility") or "All engineering branches", "year": raw.get("year") or "2025 / 2026", "type": raw.get("type") or raw.get("eventType") or "Opportunity", "mode": raw.get("mode") or "See organizer page", "startAt": raw.get("startAt"), "endAt": raw.get("endAt"), "deadline": raw.get("deadline") or raw.get("deadlineAt") or "Rolling", "deadlineAt": raw.get("deadlineAt"), "summary": raw.get("summary") or raw.get("description") or "Explore this engineering opportunity.", "description": raw.get("description") or raw.get("summary") or "Details available from the organizer.", "eligibility": raw.get("eligibility") or "Check the organizer page for eligibility details.", "applyUrl": raw.get("applyUrl") or raw.get("registrationUrl") or raw.get("url") or "#", "sourceUrl": raw.get("sourceUrl"), "sourceType": raw.get("sourceType") or raw.get("source_type") or "", "sourceStatus": raw.get("sourceStatus") or "verified", "visibility": raw.get("visibility") or "published", "state": raw.get("state") or "Telangana", "district": raw.get("district") or raw.get("area") or "Warangal", "area": raw.get("area") or raw.get("district") or "Warangal", "confidence": raw.get("confidence"), "tags": raw.get("tags") or [raw.get("type") or "Opportunity"]}

def has_official_source(event: dict[str, Any]) -> bool:
    url = str(event.get("sourceUrl") or "").strip()
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return parsed.scheme == "https" and (host.endswith(".edu.in") or host.endswith(".ac.in") or host.endswith(".org.in"))

def publishable_event(event: dict[str, Any]) -> bool:
    required = (event.get("title"), event.get("organizer"), event.get("institution"), event.get("sourceUrl"))
    status_value = str(event.get("sourceStatus", "")).lower()
    has_date_or_deadline = bool(event.get("startAt") or event.get("endAt") or event.get("deadlineAt"))
    status_allowed = status_value in {"verified", "needs_review", "unverified"}
    return (str(event.get("visibility", "published")).lower() in {"published", "needs_review"} and status_allowed and all(required) and has_date_or_deadline)

def load_events() -> list[dict[str, Any]]:
    raw = read_json(EVENTS_FILE, [])
    if isinstance(raw, dict): raw = raw.get("events", [])
    items = [normalize_event(e, i) for i, e in enumerate(raw)] if isinstance(raw, list) else []
    return [e for e in items if publishable_event(e) and str(e.get("state", "Telangana")).lower() == "telangana"]

def token_for(email: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"email": email, "exp": int(datetime.now(timezone.utc).timestamp()) + 60 * 60 * 24 * 7}, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + sig

def email_from_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in to continue")
    try:
        payload, sig = authorization.split(" ", 1)[1].split(".", 1)
        if not hmac.compare_digest(sig, hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()): raise ValueError
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if int(data["exp"]) < int(datetime.now(timezone.utc).timestamp()): raise ValueError
        return normalize_email(str(data["email"]))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please sign in again")

def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {"email": user["email"], "name": user.get("name") or user["email"].split("@")[0], "created_at": user.get("created_at")}

def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    email = email_from_token(authorization)
    users = read_users()
    user = users.get(email)
    if not user: raise HTTPException(status_code=401, detail="Account not found")
    return user

@app.get("/api/health")
def health() -> dict[str, Any]:
    raw = read_json(EVENTS_FILE, [])
    if isinstance(raw, dict): raw = raw.get("events", [])
    items = [normalize_event(e, i) for i, e in enumerate(raw)] if isinstance(raw, list) else []
    published = [e for e in items if publishable_event(e) and str(e.get("state", "Telangana")).lower() == "telangana"]
    return {"status":"ok", "service":"opportunity-atlas-api", "events":len(published), "source_records":len(raw) if isinstance(raw, list) else 0, "source_file_found":EVENTS_FILE.exists(), "verified_records":sum(1 for e in items if str(e.get("sourceStatus", "")).lower() == "verified"), "dated_records":sum(1 for e in items if e.get("startAt") or e.get("endAt") or e.get("deadlineAt")), "official_url_records":sum(1 for e in items if has_official_source(e)), "build":os.getenv("RENDER_GIT_COMMIT", "unknown")[:7]}

@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterCredentials) -> dict[str, Any]:
    email = normalize_email(payload.email)
    pin = payload.recovery_pin.strip()
    if not EMAIL_RE.fullmatch(email): raise HTTPException(status_code=422, detail="Use a valid Gmail address")
    if len(payload.password) < 8: raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    if not re.fullmatch(r"\d{4,12}", pin): raise HTTPException(status_code=422, detail="Screen lock / recovery PIN must be 4â€“12 digits")
    with LOCK:
        users = read_users()
        if email in users: raise HTTPException(status_code=409, detail="An account with this email already exists")
        users[email] = {"email":email, "name":payload.name.strip(), "password_hash":bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode(), "recovery_pin_hash":bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode(), "created_at":datetime.now(timezone.utc).isoformat()}
        write_users(users)
    user = users[email]
    return {"token":token_for(email), "user":public_user(user)}

@app.post("/api/auth/login")
def login(payload: Credentials) -> dict[str, Any]:
    email = normalize_email(payload.email)
    users = read_users()
    user = users.get(email)
    stored_hash = str(user.get("password_hash") or "") if user else ""
    try:
        valid_password = bool(user and stored_hash and bcrypt.checkpw(payload.password.encode(), stored_hash.encode()))
    except (ValueError, TypeError):
        valid_password = False
    if not user:
        raise HTTPException(status_code=401, detail="Account not found. Please create a new account.")
    if not valid_password:
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return {"token":token_for(email), "user":public_user(user)}

@app.post("/api/auth/reset")
def reset_password(payload: PasswordReset) -> dict[str, Any]:
    email = normalize_email(payload.email)
    pin = payload.recovery_pin.strip()
    if not EMAIL_RE.fullmatch(email) or not re.fullmatch(r"\d{4,12}", pin):
        raise HTTPException(status_code=401, detail="Email or recovery PIN is incorrect")
    with LOCK:
        users = read_users()
        user = users.get(email)
        pin_hash = user.get("recovery_pin_hash") if user else None
        if not user or not pin_hash or not bcrypt.checkpw(pin.encode(), pin_hash.encode()):
            raise HTTPException(status_code=401, detail="Email or recovery PIN is incorrect")
        user["password_hash"] = bcrypt.hashpw(payload.new_password.encode(), bcrypt.gensalt()).decode()
        user["password_changed_at"] = datetime.now(timezone.utc).isoformat()
        users[email] = user
        write_users(users)
    return {"token":token_for(email), "user":public_user(user)}

@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"user":public_user(user)}

@app.get("/api/colleges")
def colleges(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    raw = read_json(COLLEGES_FILE, {})
    records = raw.get("records", []) if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        return []
    clean: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        name = str(record.get("name") or record.get("institution_name") or "").strip()
        district = str(record.get("district") or record.get("district_or_city") or "").strip()
        key = (name.casefold(), district.casefold())
        if not name or key in seen:
            continue
        seen.add(key)
        clean.append({"name": name, "district": district, "status": record.get("status") or "UNVERIFIED", "collegeStatus": record.get("collegeStatus") or "", "officialHomepage": record.get("officialHomepage"), "homepageStatus": record.get("homepageStatus") or "UNVERIFIED"})
    return sorted(clean, key=lambda item: (item["name"].casefold(), item["district"].casefold()))

@app.get("/api/events")
def events(area: str | None = None, college: str | None = None, branch: str | None = None, year: str | None = None, q: str | None = None, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    values = load_events()
    def matches(e: dict[str, Any]) -> bool:
        text = json.dumps(e).lower()
        return (not area or area.lower() in text) and (not college or college.lower() in text) and (not branch or branch.lower() in text) and (not year or year.lower() in text) and (not q or q.lower() in text)
    return [e for e in values if matches(e)]

@app.get("/api/me/saved")
def get_saved(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    all_saved = read_saved()
    return {"event_ids": all_saved.get(user["email"], [])}

@app.post("/api/me/saved")
def save_opportunity(payload: SavedRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    valid_ids = {e["id"] for e in load_events()}
    if payload.event_id not in valid_ids: raise HTTPException(status_code=404, detail="Opportunity not found")
    with LOCK:
        all_saved = read_saved()
        saved = list(dict.fromkeys(all_saved.get(user["email"], [])))
        if payload.event_id not in saved: saved.append(payload.event_id)
        all_saved[user["email"]] = saved
        write_saved(all_saved)
    return {"event_ids":saved}

@app.delete("/api/me/saved/{event_id}")
def remove_saved(event_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    with LOCK:
        all_saved = read_saved()
        saved = [x for x in all_saved.get(user["email"], []) if x != event_id]
        all_saved[user["email"]] = saved
        write_saved(all_saved)
    return {"event_ids":saved}

@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "index.html")

