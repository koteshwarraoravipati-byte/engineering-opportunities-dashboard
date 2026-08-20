from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import bcrypt
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "events.json"
USERS_PATH = ROOT / "users.local.json"
FRONTEND = ROOT
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB = os.getenv("MONGODB_DB", "opportunity_atlas")
AUTH_SECRET = os.getenv("AUTH_JWT_SECRET", "").strip()
AUTH_TTL_HOURS = int(os.getenv("AUTH_TOKEN_TTL_HOURS", "168"))
CORS_ORIGINS = [item.strip() for item in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",") if item.strip()]

if not AUTH_SECRET:
    # Local/demo fallback only. Render production must set AUTH_JWT_SECRET.
    AUTH_SECRET = "local-development-only-change-me"

app = FastAPI(title="Engineering Opportunities Dashboard", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
app.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")


class EventCreate(BaseModel):
    title: str = Field(min_length=4, max_length=180)
    summary: str = Field(min_length=10, max_length=1000)
    eventType: Literal["hackathon", "workshop", "internship", "seminar", "webinar", "conference", "competition", "bootcamp", "other"]
    mode: Literal["online", "offline", "hybrid", "unknown"] = "unknown"
    startAt: datetime
    endAt: datetime | None = None
    venue: str = "Not yet confirmed"
    organizer: str = Field(min_length=2, max_length=160)
    institution: str = Field(min_length=2, max_length=160)
    registrationUrl: HttpUrl
    sourceUrl: HttpUrl
    sourceType: Literal["official_college", "approved_partner", "manual"] = "manual"
    tags: list[str] = []


class RegisterRequest(BaseModel):
    fullName: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class SavedOpportunityRequest(BaseModel):
    eventId: str = Field(min_length=3, max_length=80)


class EventStore:
    """Uses MongoDB Atlas when MONGODB_URI exists; otherwise preserves local demo data in JSON."""

    def __init__(self) -> None:
        self.collection = None
        self.users_collection = None
        if MONGODB_URI:
            try:
                from pymongo import MongoClient
                client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
                client.admin.command("ping")
                database = client[MONGODB_DB]
                self.collection = database["events"]
                self.users_collection = database["users"]
                self.collection.create_index("id", unique=True)
                self.collection.create_index([("visibility", 1), ("startAt", 1)])
                self.users_collection.create_index("email", unique=True)
                # Preserve the verified JSON records during the first Atlas startup.
                if self.collection.count_documents({}) == 0 and DATA_PATH.exists():
                    seed_events = json.loads(DATA_PATH.read_text(encoding="utf-8"))
                    if seed_events:
                        self.collection.insert_many(seed_events)
            except Exception as exc:
                raise RuntimeError("MongoDB is configured but unavailable. Check MONGODB_URI and Atlas network access.") from exc

    @property
    def mode(self) -> str:
        return "mongodb" if self.collection is not None else "seed-json"

    def all(self) -> list[dict]:
        if self.collection is None:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        return [{key: value for key, value in record.items() if key != "_id"} for record in self.collection.find({})]

    def save_all(self, events: list[dict]) -> None:
        if self.collection is None:
            DATA_PATH.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
            return
        self.collection.delete_many({})
        if events:
            self.collection.insert_many(events)

    def insert(self, event: dict) -> None:
        if self.collection is None:
            events = self.all()
            events.append(event)
            self.save_all(events)
        else:
            self.collection.insert_one(event)

    def update(self, event_id: str, patch: dict) -> dict | None:
        if self.collection is None:
            events = self.all()
            for event in events:
                if event["id"] == event_id:
                    event.update(patch)
                    self.save_all(events)
                    return event
            return None
        from pymongo import ReturnDocument
        record = self.collection.find_one_and_update({"id": event_id}, {"$set": patch}, return_document=ReturnDocument.AFTER)
        if record is None:
            return None
        record.pop("_id", None)
        return record

    def users(self) -> list[dict]:
        if self.users_collection is not None:
            return [{key: value for key, value in record.items() if key != "_id"} for record in self.users_collection.find({})]
        if not USERS_PATH.exists():
            return []
        return json.loads(USERS_PATH.read_text(encoding="utf-8"))

    def save_users(self, users: list[dict]) -> None:
        if self.users_collection is not None:
            self.users_collection.delete_many({})
            if users:
                self.users_collection.insert_many(users)
            return
        USERS_PATH.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")

    def insert_user(self, user: dict) -> None:
        if self.users_collection is not None:
            self.users_collection.insert_one(user)
            return
        users = self.users()
        users.append(user)
        self.save_users(users)

    def find_user(self, email: str) -> dict | None:
        normalized = email.lower().strip()
        if self.users_collection is not None:
            record = self.users_collection.find_one({"email": normalized})
            if record:
                record.pop("_id", None)
            return record
        return next((user for user in self.users() if user["email"] == normalized), None)

    def update_user(self, user_id: str, patch: dict) -> dict | None:
        if self.users_collection is not None:
            from pymongo import ReturnDocument
            record = self.users_collection.find_one_and_update({"id": user_id}, {"$set": patch}, return_document=ReturnDocument.AFTER)
            if record:
                record.pop("_id", None)
            return record
        users = self.users()
        for user in users:
            if user["id"] == user_id:
                user.update(patch)
                self.save_users(users)
                return user
        return None


store = EventStore()


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_email(value: str) -> str:
    email = value.lower().strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return email


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "fullName": user["fullName"],
        "email": user["email"],
        "role": user.get("role", "student"),
        "savedEventIds": user.get("savedEventIds", []),
        "createdAt": user["createdAt"],
    }


def issue_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user["id"],
        "role": user.get("role", "student"),
        "iat": now,
        "exp": now + timedelta(hours=AUTH_TTL_HOURS),
        "iss": "opportunity-atlas",
    }
    return jwt.encode(claims, AUTH_SECRET, algorithm="HS256")


def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in required")
    try:
        payload = jwt.decode(authorization.split(" ", 1)[1], AUTH_SECRET, algorithms=["HS256"], issuer="opportunity-atlas")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.") from exc
    user = next((candidate for candidate in store.users() if candidate["id"] == payload.get("sub")), None)
    if not user:
        raise HTTPException(status_code=401, detail="Account not found")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "environment": "production" if store.mode == "mongodb" else "local-demo", "dataMode": store.mode, "auth": "email-password"}


@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterRequest) -> dict:
    email = normalized_email(payload.email)
    if store.find_user(email):
        raise HTTPException(status_code=409, detail="An account already exists for this email. Please sign in.")
    user = {
        "id": f"usr-{uuid4().hex[:12]}",
        "fullName": " ".join(payload.fullName.split()),
        "email": email,
        "passwordHash": bcrypt.hashpw(payload.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        "role": "student",
        "savedEventIds": [],
        "createdAt": timestamp(),
        "updatedAt": timestamp(),
    }
    store.insert_user(user)
    return {"token": issue_token(user), "user": public_user(user)}


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict:
    user = store.find_user(normalized_email(payload.email))
    if not user or not bcrypt.checkpw(payload.password.encode("utf-8"), user["passwordHash"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return {"token": issue_token(user), "user": public_user(user)}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return public_user(user)


@app.get("/api/me/saved")
def saved_opportunities(user: dict = Depends(current_user)) -> list[dict]:
    saved_ids = set(user.get("savedEventIds", []))
    return [event for event in store.all() if event["id"] in saved_ids and event.get("visibility") == "published"]


@app.post("/api/me/saved")
def save_opportunity(payload: SavedOpportunityRequest, user: dict = Depends(current_user)) -> dict:
    event = next((event for event in store.all() if event["id"] == payload.eventId and event.get("visibility") == "published"), None)
    if not event:
        raise HTTPException(status_code=404, detail="Published opportunity not found")
    saved = user.get("savedEventIds", [])
    if payload.eventId not in saved:
        saved.append(payload.eventId)
    updated = store.update_user(user["id"], {"savedEventIds": saved, "updatedAt": timestamp()})
    return public_user(updated or user)


@app.delete("/api/me/saved/{event_id}")
def remove_saved_opportunity(event_id: str, user: dict = Depends(current_user)) -> dict:
    saved = [item for item in user.get("savedEventIds", []) if item != event_id]
    updated = store.update_user(user["id"], {"savedEventIds": saved, "updatedAt": timestamp()})
    return public_user(updated or user)


@app.get("/api/events")
def list_events(
    q: str | None = None,
    event_type: str | None = Query(default=None, alias="type"),
    mode: str | None = None,
    status: Literal["published", "review", "all"] = "published",
) -> list[dict]:
    events = store.all()
    if status == "published":
        events = [e for e in events if e["visibility"] == "published"]
    elif status == "review":
        events = [e for e in events if e["visibility"] != "published" or e["sourceStatus"] == "needs_review"]
    if event_type:
        events = [e for e in events if e["eventType"] == event_type]
    if mode:
        events = [e for e in events if e["mode"] == mode]
    if q:
        needle = q.lower().strip()
        events = [e for e in events if needle in " ".join([e["title"], e["summary"], e["organizer"], e["institution"], " ".join(e["tags"])]).lower()]
    return sorted(events, key=lambda e: e["startAt"])


@app.get("/api/events/{event_id}")
def get_event(event_id: str) -> dict:
    for event in store.all():
        if event["id"] == event_id:
            return event
    raise HTTPException(status_code=404, detail="Event not found")


@app.get("/api/analytics/overview")
def overview() -> dict:
    events = store.all()
    published = [e for e in events if e["visibility"] == "published"]
    return {
        "published": len(published),
        "needsReview": len([e for e in events if e["sourceStatus"] == "needs_review"]),
        "institutions": len({e["institution"] for e in published}),
        "sourceHealth": round(sum(e["confidence"] for e in published) / len(published) * 100) if published else 0,
        "byType": {kind: len([e for e in published if e["eventType"] == kind]) for kind in ["hackathon", "workshop", "internship", "seminar"]},
    }


@app.post("/api/admin/events", status_code=201)
def create_event(payload: EventCreate, _: dict = Depends(require_admin)) -> dict:
    """Authenticated administrator intake; events stay private until reviewer approval."""
    if payload.endAt and payload.endAt < payload.startAt:
        raise HTTPException(status_code=422, detail="endAt must be after startAt")
    event = payload.model_dump(mode="json")
    event.update({
        "id": f"evt-{uuid4().hex[:10]}", "sourceStatus": "needs_review", "visibility": "draft",
        "confidence": 0.0, "lastCheckedAt": timestamp(), "deadlineAt": None,
    })
    store.insert(event)
    return event


@app.post("/api/admin/events/{event_id}/publish")
def publish_event(event_id: str, _: dict = Depends(require_admin)) -> dict:
    """Authenticated administrator publishing endpoint."""
    event = store.update(event_id, {"visibility": "published", "sourceStatus": "verified", "lastCheckedAt": timestamp()})
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.get("/")
def homepage() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")
