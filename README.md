# Engineering Opportunities Dashboard

A student-first portal for verified engineering opportunities across India.

## Current behavior
- Responsive portal with the existing card-based visual design, search, location, college, branch and graduation-year filters.
- India-wide state/UT filters, seeded with verified official opportunities and clearly separated review/source-lead lanes.
- Dated listings are separated into institution-verified opportunities, source leads/review records, and clearly labelled company-led programs. Company-provider records include fees, training type, affiliation notes and a source-check date.
- Undated or uncertain records remain in review and are not shown publicly.
- Fully ended opportunities are archived from the public catalog; future events with passed deadlines are labelled for organizer confirmation.
- Each published card links back to its official college/university source page.

## Source and verification policy
Google/search engines may be used to discover leads. Institution-verified listings require an official engineering-college or university page. Separately labelled company-provider listings may use the provider’s own page, with concrete dates, fees where disclosed, and an explicit affiliation disclaimer. Copied social posts, expired records, unclear dates and duplicate records are excluded from new upcoming additions. Provider claims must never be presented as independently verified institutional endorsement. The collector discovers candidates only; it never auto-publishes them.

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

Company-provider records use `sourceType: company_provider` and `sourceStatus: unverified`. They appear in a separate Company-led programs section, not the verified lane. Undated PHN pages are linked only in a provider directory, not counted as open opportunities. Training marketed with an internship letter is not an employment offer.

## Admin management

Open `/admin` and sign in with an existing server-authorized Atlas account. The owner-authorized initial administrator is `koteshwarraoravipati@gmail.com`; override `ADMIN_EMAILS` on the API host with a comma-separated allowlist (an empty value disables admin access). Public registration cannot create accounts for reserved admin addresses.

Admins can create, edit, draft, archive, and delete opportunities. All `/api/admin/events` operations enforce server-side authentication and authorization. Public `/api/catalog/overrides` returns only publishable changes and hidden/deleted IDs; the student dashboard merges these with its static seed on refresh.

Configure `MONGODB_URI` for durable `event_overrides` storage across Render deployments. Without MongoDB, overrides use `data/event_overrides.json` and need a persistent disk. Session signing uses `SESSION_SECRET` if configured, otherwise a random key persisted in MongoDB or local storage; older sessions may require signing in again after migration. Never set a publicly known session secret.

Tests: `uv run --no-project --with fastapi --with httpx --with bcrypt --with pymongo --with pytest python -m pytest test_admin.py -q`.

## Company program update (4 November 2026)

Added five Techobytes program batches, one World Technocon online workshop, and India Space Lab Batch 2 (notice hosted by IIT Bhubaneswar, not an IIT-operated internship). PHN is directory-only because no current dated intake was established. Ambiguous online bootcamp years and conflicting Technocon campus/mode listings were excluded. See `PROGRAM_SOURCES.md` for the evidence and limitations.
