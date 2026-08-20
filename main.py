from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "events.json"
FRONTEND = ROOT
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB = os.getenv("MONGODB_DB", "opportunity_atlas")
CORS_ORIGINS = [item.strip() for item in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",") if item.strip()]

app = FastAPI(title="Engineering Opportunities Dashboard", version="0.2.0")
app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
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


class EventStore:
        """Uses MongoDB Atlas when MONGODB_URI exists; otherwise preserves local demo data in JSON."""

    def __init__(self) -> None:
                self.collection = None
                if MONGODB_URI:
                                try:
                                                    from pymongo import MongoClient
                                                    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
                                                    client.admin.command("ping")
                                                    self.collection = client[MONGODB_DB]["events"]
                                                    self.collection.create_index("id", unique=True)
                                                    self.collection.create_index([("visibility", 1), ("startAt", 1)])
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
                                            record = self.collection.find_one_and_update({"id": event_id}, {"$set": patch}, return_document=True)
        if record is None:
                        return None
        record.pop("_id", None)
        return record


store = EventStore()


def timestamp() -> str:
        return datetime.now().astimezone().isoformat()


@app.get("/api/health")
def health() -> dict:
        return {"status": "ok", "environment": "production" if store.mode == "mongodb" else "local-demo", "dataMode": store.mode}


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
def create_event(payload: EventCreate) -> dict:
        """Intake endpoint; events stay private until reviewer approval. Add auth before public deployment."""
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
def publish_event(event_id: str) -> dict:
        """Development-only endpoint. Protect with administrator authentication before public launch."""
    event = store.update(event_id, {"visibility": "published", "sourceStatus": "verified", "lastCheckedAt": timestamp()})
    if event is None:
                raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.get("/")
def homepage() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")
