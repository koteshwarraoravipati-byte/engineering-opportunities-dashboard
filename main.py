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
SECRET = os.getenv("SESSION_SECRET", "opportunity-atlas-dev-secret-change-me").encode()
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@gmail\.com$", re.I)
LOCK = threading.Lock()

app = FastAPI(title="Opportunity Atlas API", version="2.0.0")
configured_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
origins = ["*"] if "*" in configured_origins else list(dict.fromkeys(configured_origins + ["https://eod-warangal.vercel.app", "https://engineering-opportunities-dashboard.vercel.app"]))
app.add_middleware(CORSMiddleware, allow_origins=origins if origins else ["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

FALLBACK_EVENTS = [
    {"id":"warangal-1","title":"Graduate Software Engineer","organization":"Tech Mahindra","location":"Warangal, Telangana","area":"Warangal","college":"Any college","branch":"CSE / IT / ECE","year":"2025 / 2026","type":"Full-time","deadline":"30 Sep 2026","summary":"Build customer-facing software with a structured engineering onboarding programme.","description":"An early-career engineering role for students and recent graduates who enjoy problem solving, APIs, and collaborative delivery.","eligibility":"B.Tech / B.E. students and graduates in CSE, IT, or ECE. Strong programming fundamentals preferred.","applyUrl":"https://careers.techmahindra.com/","tags":["Software","Graduate","Warangal"]},
    {"id":"warangal-2","title":"Frontend Development Internship","organization":"SR Innovation Hub","location":"Warangal, Telangana","area":"Warangal","college":"SR University","branch":"CSE / IT","year":"2026","type":"Internship","deadline":"15 Oct 2026","summary":"Ship accessible web experiences alongside mentors from the local engineering community.","description":"A practical internship focused on modern frontend development, product thinking, and portfolio-ready work.","eligibility":"Current B.Tech students in CSE or IT with HTML, CSS, and JavaScript fundamentals.","applyUrl":"https://www.sru.edu.in/","tags":["Frontend","Internship","Warangal"]},
    {"id":"warangal-3","title":"Data & AI Challenge 2026","organization":"T-Hub Community","location":"Warangal / Hybrid","area":"Warangal","college":"Any college","branch":"All engineering branches","year":"2025 / 2026","type":"Challenge","deadline":"01 Nov 2026","summary":"Solve a real-world Telangana problem and present your prototype to industry judges.","description":"A team challenge with workshops, expert feedback, and an opportunity to turn a strong prototype into a career conversation.","eligibility":"Open to engineering students and recent graduates. Teams of 2–4 are welcome.","applyUrl":"https://t-hub.co/","tags":["AI","Challenge","Hybrid"]}
]

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
    return {"id": str(raw.get("id") or raw.get("event_id") or f"opportunity-{index}"), "title": raw.get("title") or raw.get("name") or "Engineering opportunity", "organization": raw.get("organization") or raw.get("organizer") or raw.get("company") or "Local engineering community", "institution": raw.get("institution") or raw.get("college") or raw.get("organization") or "Warangal engineering community", "location": raw.get("location") or raw.get("venue") or "Warangal, Telangana", "venue": raw.get("venue") or raw.get("location") or "Warangal, Telangana", "area": raw.get("area") or "Warangal", "college": raw.get("college") or raw.get("institution") or "Any college", "branch": raw.get("branch") or raw.get("eligibility") or "All engineering branches", "year": raw.get("year") or "2025 / 2026", "type": raw.get("type") or raw.get("eventType") or "Opportunity", "mode": raw.get("mode") or "See organizer page", "startAt": raw.get("startAt"), "endAt": raw.get("endAt"), "deadline": raw.get("deadline") or raw.get("deadlineAt") or "Rolling", "deadlineAt": raw.get("deadlineAt"), "summary": raw.get("summary") or raw.get("description") or "Explore this engineering opportunity.", "description": raw.get("description") or raw.get("summary") or "Details available from the organizer.", "eligibility": raw.get("eligibility") or "Check the organizer page for eligibility details.", "applyUrl": raw.get("applyUrl") or raw.get("registrationUrl") or raw.get("url") or "#", "sourceUrl": raw.get("sourceUrl"), "sourceStatus": raw.get("sourceStatus") or "verified", "confidence": raw.get("confidence"), "tags": raw.get("tags") or [raw.get("type") or "Opportunity"]}

def load_events() -> list[dict[str, Any]]:
    raw = read_json(EVENTS_FILE, [])
    if isinstance(raw, dict): raw = raw.get("events", [])
    items = [normalize_event(e, i) for i, e in enumerate(raw)] if isinstance(raw, list) else []
    published = [e for e in items if str(e.get("visibility", "published")).lower() == "published"]
    warangal = [e for e in published if "warangal" in json.dumps(e).lower()]
    return warangal if warangal else FALLBACK_EVENTS

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
        return str(data["email"]).lower()
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please sign in again")

def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {"email": user["email"], "name": user.get("name") or user["email"].split("@")[0], "created_at": user.get("created_at")}

def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    email = email_from_token(authorization)
    users = read_json(USERS_FILE, {})
    user = users.get(email)
    if not user: raise HTTPException(status_code=401, detail="Account not found")
    return user

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status":"ok", "service":"opportunity-atlas-api", "events":len(load_events())}

@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterCredentials) -> dict[str, Any]:
    email = payload.email.strip().lower()
    pin = payload.recovery_pin.strip()
    if not EMAIL_RE.fullmatch(email): raise HTTPException(status_code=422, detail="Use a valid Gmail address")
    if len(payload.password) < 8: raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    if not re.fullmatch(r"\d{4,12}", pin): raise HTTPException(status_code=422, detail="Screen lock / recovery PIN must be 4–12 digits")
    with LOCK:
        users = read_json(USERS_FILE, {})
        if email in users: raise HTTPException(status_code=409, detail="An account with this email already exists")
        users[email] = {"email":email, "name":payload.name.strip(), "password_hash":bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode(), "recovery_pin_hash":bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode(), "created_at":datetime.now(timezone.utc).isoformat()}
        write_json(USERS_FILE, users)
    user = users[email]
    return {"token":token_for(email), "user":public_user(user)}

@app.post("/api/auth/login")
def login(payload: Credentials) -> dict[str, Any]:
    email = payload.email.strip().lower()
    users = read_json(USERS_FILE, {})
    user = users.get(email)
    if not user or not bcrypt.checkpw(payload.password.encode(), user["password_hash"].encode()): raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return {"token":token_for(email), "user":public_user(user)}

@app.post("/api/auth/reset")
def reset_password(payload: PasswordReset) -> dict[str, Any]:
    email = payload.email.strip().lower()
    pin = payload.recovery_pin.strip()
    if not EMAIL_RE.fullmatch(email) or not re.fullmatch(r"\d{4,12}", pin):
        raise HTTPException(status_code=401, detail="Email or recovery PIN is incorrect")
    with LOCK:
        users = read_json(USERS_FILE, {})
        user = users.get(email)
        pin_hash = user.get("recovery_pin_hash") if user else None
        if not user or not pin_hash or not bcrypt.checkpw(pin.encode(), pin_hash.encode()):
            raise HTTPException(status_code=401, detail="Email or recovery PIN is incorrect")
        user["password_hash"] = bcrypt.hashpw(payload.new_password.encode(), bcrypt.gensalt()).decode()
        user["password_changed_at"] = datetime.now(timezone.utc).isoformat()
        users[email] = user
        write_json(USERS_FILE, users)
    return {"token":token_for(email), "user":public_user(user)}

@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"user":public_user(user)}

@app.get("/api/events")
def events(area: str | None = None, college: str | None = None, branch: str | None = None, year: str | None = None, q: str | None = None, user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    values = load_events()
    def matches(e: dict[str, Any]) -> bool:
        text = json.dumps(e).lower()
        return (not area or area.lower() in text) and (not college or college.lower() in text) and (not branch or branch.lower() in text) and (not year or year.lower() in text) and (not q or q.lower() in text)
    return [e for e in values if matches(e)]

@app.get("/api/me/saved")
def get_saved(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    all_saved = read_json(SAVED_FILE, {})
    return {"event_ids": all_saved.get(user["email"], [])}

@app.post("/api/me/saved")
def save_opportunity(payload: SavedRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    valid_ids = {e["id"] for e in load_events()}
    if payload.event_id not in valid_ids: raise HTTPException(status_code=404, detail="Opportunity not found")
    with LOCK:
        all_saved = read_json(SAVED_FILE, {})
        saved = list(dict.fromkeys(all_saved.get(user["email"], [])))
        if payload.event_id not in saved: saved.append(payload.event_id)
        all_saved[user["email"]] = saved
        write_json(SAVED_FILE, all_saved)
    return {"event_ids":saved}

@app.delete("/api/me/saved/{event_id}")
def remove_saved(event_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    with LOCK:
        all_saved = read_json(SAVED_FILE, {})
        saved = [x for x in all_saved.get(user["email"], []) if x != event_id]
        all_saved[user["email"]] = saved
        write_json(SAVED_FILE, all_saved)
    return {"event_ids":saved}

@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "index.html")
