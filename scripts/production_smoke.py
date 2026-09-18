#!/usr/bin/env python3
"""Read-only production smoke checks for Opportunity Atlas."""
from __future__ import annotations
import json
import os
from urllib.request import Request, urlopen

FRONTEND = os.getenv("ATLAS_FRONTEND_URL", "https://eod-warangal.vercel.app").rstrip("/")
API = os.getenv("ATLAS_API_URL", "https://engineering-opportunities-dashboard.onrender.com").rstrip("/")

def get(url: str):
    request = Request(url, headers={"User-Agent": "OpportunityAtlasSmoke/1.0"})
    with urlopen(request, timeout=25) as response:
        body = response.read()
        return response.status, response.headers, body

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"SMOKE FAIL: {message}")

status, headers, home = get(FRONTEND + "/")
require(status == 200, f"frontend returned HTTP {status}")
text = home.decode("utf-8", errors="replace")
for marker in ("STATIC_CATALOG", "data-load-more", "pageshow", "assistantModal"):
    require(marker in text, f"frontend marker missing: {marker}")

status, headers, catalog_body = get(FRONTEND + "/catalog.json")
require(status == 200, f"catalog returned HTTP {status}")
catalog = json.loads(catalog_body.decode("utf-8"))
records = catalog.get("events") if isinstance(catalog, dict) else None
require(isinstance(records, list) and records, "catalog has no published records")
require(all(str(record.get("visibility", "published")).lower() == "published" for record in records), "archived record leaked into static catalog")

status, headers, health_body = get(API + "/api/health")
require(status == 200, f"API health returned HTTP {status}")
health = json.loads(health_body.decode("utf-8"))
require(health.get("status") == "ok", "API health status is not ok")
require(health.get("source_file_found") is True, "event source file is missing")
require(int(health.get("events", 0)) > 0, "API has no published events")
require(int(health.get("archived_records", 0)) >= 0, "archived record metric missing")
if health.get("assistant_configured") and health.get("assistant_last_error"):
    raise SystemExit("SMOKE FAIL: configured assistant reports " + str(health["assistant_last_error"]))

print(json.dumps({"frontend": "ok", "catalog_events": len(records), "api": "ok", "health": health}, indent=2))

