# Deployment sequence — Vercel + Render + MongoDB Atlas

## Prerequisites
- A GitHub repository containing this project.
- A MongoDB Atlas project/cluster and a database user restricted to the required database.
- Render and Vercel accounts connected to the GitHub repository.

## 1. Provision MongoDB Atlas
1. Create a cluster and database named `opportunity_atlas`.
2. Create a database user with the minimum needed permissions for this application.
3. Add the Render service outbound network access according to Atlas's current network-access guidance.
4. Copy the **URI only** into Render's secret environment-variable field; never place it in source control.

## 2. Deploy API on Render
1. Create a Render Web Service from the repository root.
2. Render reads `render.yaml`; use `requirements.txt` to build and the listed Uvicorn start command.
3. Add secrets: `MONGODB_URI` and `CORS_ORIGINS` (temporarily the local URL plus the final Vercel URL after it exists).
4. Verify `<render-url>/api/health`, `/docs`, and `/api/events`.

## 3. Deploy portal on Vercel
1. Set the project root to the repository root; Vercel uses `frontend` as the output directory through `vercel.json`.
2. Once Render provides its public HTTPS URL, update `frontend/config.js` with that exact URL and commit the change.
3. Deploy and verify search/filter functions against the Render API.
4. Add the final Vercel URL to Render `CORS_ORIGINS` and redeploy/restart Render.

## 4. Production checks before launch
- Add authentication to every `/api/admin/*` route before exposing it publicly.
- Replace demo records with source-verified institutional records.
- Confirm every collector respects the relevant site's terms and robots policy.
- Test mobile view, review flow, invalid data, CORS behavior, and HTTPS links.
- Set backups, monitoring, rate limiting, privacy notice, and a source-removal contact.

## Current limit
The project is deployment-ready, but it deliberately does not attempt to create or use any external accounts or databases. The owner must authenticate to MongoDB Atlas, Render, Vercel, and GitHub before actual publication.
