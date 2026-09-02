# Engineering Opportunities Dashboard

A student-first portal for verified engineering opportunities across Telangana.

## Current behavior
- Responsive portal with the existing card-based visual design, search, location, college, branch and graduation-year filters.
- Telangana-wide location scope, currently seeded with verified official opportunities from Warangal, Hyderabad and Sangareddy.
- Public records are shown only when they have a concrete date or deadline, an organizer/institution, a direct HTTPS source URL on an official institution domain, and an explicit `verified` status.
- Undated or uncertain records remain in review and are not shown publicly.
- No synthetic fallback opportunities are displayed when the verified dataset is empty.
- Each published card links back to its official college/university source page.

## Source and verification policy
Google/search engines may be used to discover leads. The official engineering-college or university page is the only evidence accepted for publication. Third-party-only listings, copied social posts, expired records, unclear dates, duplicate records and unverified claims are blocked. The collector discovers candidates only; it never auto-publishes them.

## Run locally

```powershell
uv sync
uv run uvicorn main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`.

## Data workflow
1. Maintain approved official institution domains in `sources.json`.
2. Run `collector.py` to create review candidates.
3. Verify the original official page, date/status, organizer, relevance, eligibility and application link.
4. Add only reviewed records to `events.json` with `visibility: published` and `sourceStatus: verified`.
5. The API performs a second publication guard before returning records.

Third-party platforms remain blocked: Google can discover a lead, but a third-party-only listing is never published without an official college evidence page.
