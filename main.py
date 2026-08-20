from __future__ import annotations
import json, os
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl
ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "events.json"
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB = os.getenv("MONGODB_DB", "opportunity_atlas")
CORS_ORIGINS = [v.strip() for v in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",") if v.strip()]
app = FastAPI(title="Engineering Opportunities Dashboard", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
app.mount("/assets", StaticFiles(directory=ROOT), name="assets")
client = None
collection = None
if MONGODB_URI: from pymongo import MongoClient; client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000); client.admin.command("ping"); collection = client[MONGODB_DB]["events"]; collection.create_index("id", unique=True); collection.create_index([("visibility", 1), ("startAt", 1)]); collection.count_documents({}) == 0 and collection.insert_many(json.loads(DATA_PATH.read_text(encoding="utf-8")))
def all_events(): return json.loads(DATA_PATH.read_text(encoding="utf-8")) if collection is None else [{k:v for k,v in item.items() if k != "_id"} for item in collection.find({})]
def save_events(events): return DATA_PATH.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8") if collection is None else (collection.delete_many({}), collection.insert_many(events) if events else None)
def checked_time(): return datetime.now().astimezone().isoformat()
@app.get("/api/health")
def health(): return {"status":"ok", "environment":"production" if collection is not None else "local-demo", "dataMode":"mongodb" if collection is not None else "seed-json"}
@app.get("/api/events")
def list_events(q: str|None=None, event_type: str|None=Query(default=None, alias="type"), mode: str|None=None, status: str="published"): return sorted([e for e in all_events() if (status != "published" or e.get("visibility") == "published") and (not event_type or e.get("eventType") == event_type) and (not mode or e.get("mode") == mode) and (not q or q.lower().strip() in " ".join([str(e.get("title","")), str(e.get("summary","")), str(e.get("organizer","")), str(e.get("institution","")), " ".join(e.get("tags",[]))]).lower())], key=lambda e:e["startAt"])
@app.get("/api/events/{event_id}")
def get_event(event_id: str): return next((e for e in all_events() if e.get("id") == event_id), (_ for _ in ()).throw(HTTPException(status_code=404, detail="Event not found")))
@app.get("/api/analytics/overview")
def overview():
    published=[e for e in all_events() if e.get("visibility") == "published"]
    return {"published":len(published),"needsReview":len([e for e in all_events() if e.get("sourceStatus") == "needs_review"]),"institutions":len({e.get("institution") for e in published}),"sourceHealth":round(sum(e.get("confidence",0) for e in published)/len(published)*100) if published else 0,"byType":{k:len([e for e in published if e.get("eventType")==k]) for k in ["hackathon","workshop","internship","seminar"]}}
@app.get("/")
def homepage(): return FileResponse(ROOT / "index.html")
