# Engineering Opportunities Dashboard

A working MVP portal for viewing verified engineering opportunities across Telangana.

## What this build includes
- FastAPI REST endpoints for events, analytics, local intake, and review/publish workflow.
- Responsive web portal with search and opportunity-type/mode filters.
- Source-first event records and explicit `verified`/`needs_review` statuses.
- Clearly labeled demonstration data only; no live event claims and no automated collection yet.

## Run locally

```powershell
uv sync
uv run uvicorn backend.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000` in Google Chrome.

## API routes
- `GET /api/health`
- `GET /api/events?type=hackathon&mode=offline&q=AI`
- `GET /api/events/{id}`
- `GET /api/analytics/overview`
- `POST /api/admin/events` (creates a draft requiring review)
- `POST /api/admin/events/{id}/publish`

## Before production deployment
1. Add authentication to all `/api/admin/*` routes.
2. Replace `data/events.json` with MongoDB Atlas using encrypted environment variables.
3. Build an approved institutional-domain registry and collectors that honor each source’s terms/robots policy.
4. Obtain explicit API/partnership/written permission before automating any third-party platform such as Unstop or Internshala.
5. Add rate limiting, logging, tests, CI, error monitoring, backups, and a privacy notice.
6. Deploy the web service to a chosen host (for example Render/Railway) and connect a custom domain if required.

## Important data policy
This MVP intentionally does not scrape Google, Internshala, or Unstop. Search must be a discovery aid; the original permitted institutional page must be validated before an opportunity is published.
